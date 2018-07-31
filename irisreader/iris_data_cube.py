#!/usr/bin/env python3

"""
iris_data_cube class: abstraction that makes the data, the headers and a number
of auxiliary variables available
"""

# TODO:
# file input has to be sorted!

import numpy as np
import warnings
from datetime import timedelta

import irisreader as ir
from irisreader.utils.fits import line2extension, array2dict, CorruptFITSException
from irisreader.utils.date import from_Tformat, to_Tformat
from irisreader.utils.coordinates import iris_coordinates

DEBUG = True

# IRIS data cube class
class iris_data_cube:
    """
    This class implements an abstraction of an IRIS FITS file collection, 
    specifically it appears as one single data cube, automatically discarding
    images that are entirely null and concatenating multiple files. Moreover,
    it provides basic access to image headers. It provides the basic 
    functionalities needed for the classes sji_cube and raster_cube that then
    implement more sji and raster-specific details. Hence, this class should 
    only be used internally.
    
    Parameters
    ----------
    files : string
        Path or list of paths to the IRIS FITS file(s).
    line : string
        Line to select: this can be any unique abbreviation of the line name (e.g. "Mg"). For non-unique abbreviations, an error is thrown.
    keep_null : boolean
        Controls whether images that are NULL (-200) everywhere are removed from the data cube (keep_null=False) or not (keep_null=True).
        
        
    Attributes
    ----------
    type : str
        Observation type: 'sji' or 'raster'.
    obsid : str
        Observation ID of the selected observation.
    desc : str
        Description of the selected observation.
    start_date : str
        Start date of the selected observation.
    end_date : str
        End date of the selected observation.
    mode : str
        Observation mode of the selected observation ('sit-and-stare' or 'raster').
    line_info : str
        Description of the selected line.
    n_steps : int
        Number of time steps in the data cube (this is affected by the keep_null argument).
    primary_headers: dict
        Dictionary with primary headers of the FITS file (lazy loaded).
    time_specific_headers: dict
        List of dictionaries with time-specific headers of the selected line (lazy loaded).  
    shape : tuple
        Shape of the data cube (this is affected by the keep_null argument)
    """

    # constructor
    def __init__( self, files, line='', keep_null=False ):
                
        # if filename is not a list, create a list with one element:
        if not isinstance( files, list ):
            files = [ files ]

        # store arguments
        self._files = files
        self._line = line
        self._keep_null = keep_null
        
        # request first file from filehub and get general info
        first_file = ir.file_hub.open( files[0] )
        
        # check whether the INSTRUMENT header is either set to SJI or raster:
        if 'INSTRUME' not in first_file[0].header.keys() or not first_file[0].header['INSTRUME'] in ['SJI', 'SPEC']:
            raise CorruptFITSException( "This is neither IRIS SJI nor raster! (according to the INSTRUME header)" )
        
        # set FITS type
        if first_file[0].header['INSTRUME'] == 'SJI':
            self.type = 'sji' 
        else:
            self.type = 'raster'
            
        # get extensions with data cubes in them
        self._n_ext = len( first_file )
        data_cube_extensions = []
        for i in range( self._n_ext ):
            if hasattr( first_file[i], 'shape' ) and len( first_file[i].shape ) == 3:
                data_cube_extensions.append( i )
       
        if len( data_cube_extensions ) == 0:
            raise CorruptFITSException( "No data cubes found." )
        
        self._first_data_ext = min( data_cube_extensions )
        self._last_data_ext = max( data_cube_extensions )
        
        # find extension that contains selected line
        if line == '':
            self._selected_ext = self._first_data_ext # choose first line by default
        elif line2extension( first_file[0].header, line ) != -1: 
            self._selected_ext = line2extension( first_file[0].header, line )
        else:
            self.close()
            raise CorruptFITSException(('Change the line parameter: The desired spectral window is either not found or specified ambiguously.'))
        
        # check the integrity of this first file
        self._check_integrity( first_file )
        
        # set obsid
        self.obsid = first_file[0].header['OBSID']
        
        # set date
        self.start_date = first_file[0].header['STARTOBS']
        self.end_date = first_file[0].header['ENDOBS']

        # set description
        self.desc = first_file[0].header['OBS_DESC']

        # get observation mode
        if 'sit-and-stare' in self.desc:
            self.mode = 'sit-and-stare'
        else:
            self.mode = 'n-step raster'

        # number of files
        self.n_files = len( self._files )
            
        # line information (SJI info is replaced by actual line information)
        self.line_info = first_file[0].header['TDESC'+str(self._selected_ext-self._first_data_ext+1)]
        self.line_info = self.line_info.replace( 'SJI_1330', 'C II 1330' )
        self.line_info = self.line_info.replace( 'SJI_1400', 'Si IV 1400' )
        self.line_info = self.line_info.replace( 'SJI_2796', 'Mg II h/k 2796' )
        self.line_info = self.line_info.replace( 'SJI_2832', 'Mg II wing 2832' )
        
        # no cropping: set variables to none
        self._xmin = None
        self._xmax = None
        self._ymin = None
        self._ymax = None
        self._cropped = False
        
        # set some variables that will be lazy loaded
        self.shape = None
        self.n_steps = None
        self._valid_steps = None
        self.primary_headers = None
        self.time_specific_headers = None
        self.line_specific_headers = None
        self.headers = None
        
        # initialize coordinate converter
        self._ico = iris_coordinates( header=first_file[self._selected_ext].header, mode=self.type )


    # close all files
    def close( self ):
        """
        Closes the FITS file(s)
        """
        
        for file in self._files:
            ir.file_hub.close( file )
    
    # some components are loaded only upon first access
    def __getattribute__( self, name ):
        if name=='primary_headers' and object.__getattribute__( self, "primary_headers" ) is None:
            self._prepare_primary_headers()
            return object.__getattribute__( self, "primary_headers" )
        elif name=='_valid_steps' and object.__getattribute__( self, "_valid_steps" ) is None:
            self._prepare_valid_steps()
            return object.__getattribute__( self, "_valid_steps" )
        elif name=='n_steps' and object.__getattribute__( self, "n_steps" ) is None:
            self._prepare_valid_steps()
            return object.__getattribute__( self, "n_steps" )
        elif name=='shape' and object.__getattribute__( self, "shape" ) is None:
            self._prepare_valid_steps()
            return object.__getattribute__( self, "shape" )
        elif name=='time_specific_headers' and object.__getattribute__( self, "time_specific_headers" ) is None:
            self._prepare_time_specific_headers()
            return object.__getattribute__( self, "time_specific_headers" )
        elif name=='line_specific_headers' and object.__getattribute__( self, "line_specific_headers" ) is None:
            self._prepare_line_specific_headers()
            return object.__getattribute__( self, "line_specific_headers" )
        elif name=='headers' and object.__getattribute__( self, "headers" ) is None:
            self._prepare_combined_headers()
            return object.__getattribute__( self, "headers" )
        else:
            return object.__getattribute__( self, name )

    # prepare valid steps
    # TODO: data is read twice here.. should we add an option to do everything in RAM??
    def _prepare_valid_steps( self ):
        if DEBUG: print("DEBUG: [iris_data_cube] Lazy loading valid image steps")
        valid_steps = []
        
        # go through all the files: make sure they are not corrupt with _check_integrity
        for file_no in range( len( self._files ) ):
            
            # request file from file hub
            f = ir.file_hub.open( self._files[ file_no ] )
            
            try:
                # make sure that file is not corrupt
                self._check_integrity( f )
                
                # check whether some images are -200 everywhere and if desired
                # (keep_null=False), do not label these images as valid
                for file_step in range( f[self._selected_ext].shape[0] ):
                    if self._keep_null or not np.all( f[ self._selected_ext ].section[file_step,:,:] == -200 ):
                        valid_steps.append( [file_no, file_step] )
                        
            except CorruptFITSException as e:
                warnings.warn("File #{} is corrupt, discarding it ({})".format( file_no, e ) )
            
        # raise a warning if the data cube contains no valid steps    
        if valid_steps == []:
            warnings.warn("This data cube contains no valid images!")

        # update class instance variables
        self._valid_steps = np.array( valid_steps )
        self.n_steps = len( valid_steps )
        self.shape = tuple( [ self.n_steps ] + list( f[ self._selected_ext ].shape[1:] ) )
               
    # prepare primary headers
    def _prepare_primary_headers( self ):
        if DEBUG: print("DEBUG: [iris_data_cube] Lazy loading primary headers")
        
        # request first file from file hub
        first_file = ir.file_hub.open( self._files[0] )
        
        # convert headers to dictionary and clean up some values
        self.primary_headers = dict( first_file[0].header )
        self.primary_headers['SAA'] = self.primary_headers['SAA'].strip() 
        self.primary_headers['NAXIS'] = 2
        
        # remove empty headers
        if '' in self.primary_headers.keys():
            del self.primary_headers['']
        
        # DATE_OBS may not always be there: set it to STARTOBS
        if not 'STARTOBS' in self.primary_headers.keys() or self.primary_headers['STARTOBS'].strip() == '':
            raise ValueError( "No STARTOBS in primary header!" )
        else:
            self.primary_headers['DATE_OBS'] = self.primary_headers['STARTOBS']

        
    # prepare time-specific headers out of second last extension
    def _prepare_time_specific_headers( self ):
        if DEBUG: print("DEBUG: [iris_data_cube] Lazy loading time specific headers")
        
        time_specific_headers = []
        file_no = 0
        
        # go through all the files and read headers (avoid files that have no data or are corrupt)
        file_numbers = np.unique( self._valid_steps[:,0] ) # files with valid images
        for file_no in file_numbers:
            
            # request file from file hub
            f = ir.file_hub.open( self._files[file_no] )
            
            # read headers from data array
            file_time_specific_headers = array2dict( f[self._n_ext-2].header, f[self._n_ext-2].data )
            
            # make sure only headers for valid images are included
            file_time_specific_headers = [file_time_specific_headers[i] for i in self._get_valid_steps( file_no )]
            
            # append headers to global time_specific_headers list
            time_specific_headers += file_time_specific_headers

        # set a DATE_OBS header in each frame as DATE_OBS = STARTOBS + TIME
        startobs = from_Tformat( self.primary_headers['STARTOBS'] )
        for i in range( len( time_specific_headers ) ):
            time_specific_headers[i]['DATE_OBS'] = to_Tformat( startobs + timedelta( seconds=time_specific_headers[i]['TIME'] ) )

        self.time_specific_headers = time_specific_headers

    # prepare line specific headers
    def _prepare_line_specific_headers( self ):
        if DEBUG: print("DEBUG: [iris_data_cube] Lazy loading line specific headers")
        
        # request first file from file hub
        first_file = ir.file_hub.open( self._files[0] )
        
        # get line-specific headers from data extension (if selected extension is not the first one)
        if self._selected_ext > 0:
            line_specific_headers = dict( first_file[ self._selected_ext ].header )
        else:
            line_specific_headers = {}
        
        # add wavelnth, wavename, wavemin and wavemax (without loading primary headers)
        line_specific_headers['WAVELNTH'] = first_file[0].header['TWAVE'+str(self._selected_ext-self._first_data_ext+1)]
        line_specific_headers['WAVENAME'] = first_file[0].header['TDESC'+str(self._selected_ext-self._first_data_ext+1)]
        line_specific_headers['WAVEMIN'] =  first_file[0].header['TWMIN'+str(self._selected_ext-self._first_data_ext+1)]
        line_specific_headers['WAVEMAX'] =  first_file[0].header['TWMAX'+str(self._selected_ext-self._first_data_ext+1)]
        line_specific_headers['WAVEWIN'] =  first_file[0].header['TDET'+str(self._selected_ext-self._first_data_ext+1)]

        self.line_specific_headers = line_specific_headers

    
    # prepare line-specific headers: this function will be implemented in raster_cube / sji_cube individually
#    def _prepare_line_specific_headers( self ):
#        raise NotImplementedError()
        
    def _prepare_combined_headers( self ):
        raise NotImplementedError()
        
    # function to remove image steps from valid steps (e.g. by cropper)
    # TODO: update combined headers in raster/SJI implementation
    def _remove_steps( self, steps ):
    
        # if steps is a single integer, put it into a list    
        if not isinstance( steps, (list, tuple) ):
            steps = [steps]
    
        # now remove the steps (make sure they are removed simultaneously)
        self._valid_steps = np.delete( self._valid_steps, steps, axis=0 )
        
        # update n_steps and shape
        self.n_steps = len( self._valid_steps )
        self.shape = tuple( [ self.n_steps ] + list( self.shape[1:] ) )
        
        # update headers if already loaded
        if not object.__getattribute__( self, "time_specific_headers" ) is None:
            self._prepare_time_specific_headers()
        
    # function to find file number and file step of a given time step
    def _whereat( self, step ):
        return self._valid_steps[ step, : ]
    
    # function to return valid steps in a file
    def _get_valid_steps( self, file_no ):
        return self._valid_steps[ self._valid_steps[:,0]==file_no, 1 ]
    
    # how to behave if called as a data array
    # TODO: mention why we are not using the section interface
    def __getitem__( self, index ):
        """
        Abstracts access to the data cube. While in the get_image_step function
        data is loaded through the the section method to make sure that only
        the image requested by the user is loaded into memory, this method
        directly accesses the data object of the hdulist, allowing faster slicing
        of data. Whenever only time slices are required (i.e. single images), 
        the get_image_step function should be used instead, since access 
        through the data object can lead to memory problems.
        
        If the data cube happens to be cropped, this method will automatically
        abstract access to the cropped data. If keep_null=False, null images
        will automatically be removed from the representation.
        """
        
        # check dimensions - this rules out the ellisis (...) for the moment
        if len( index ) != 3:
            raise ValueError("This is a three-dimensional object, please index accordingly.")

        # get involved file numbers and steps
        # if index[0] is a single number (not iterable, not a slice), make a list of it
        if not hasattr( index[0], '__iter__') and not isinstance( index[0], slice ):
            valid_steps = self._valid_steps[ [index[0]], : ]
        else:
            valid_steps = self._valid_steps[ index[0], : ]
        
        # if image should be cropped make sure that slices stay slices (is about 30% faster)
        if self._cropped:  
            if isinstance( index[1], slice ):
                a = self._ymin if index[1].start is None else index[1].start+self._ymin
                b = self._ymax if index[1].stop is None else index[1].stop+self._ymin  
                internal_index1 = slice( a, b, index[1].step )
                
            else:
                internal_index1 = np.arange( self._ymin, self._ymax )[ index[1] ]
                
            if isinstance( index[2], slice ):
                a = self._xmin if index[2].start is None else index[2].start+self._xmin
                b = self._xmax if index[2].stop is None else index[2].stop+self._xmin  
                internal_index2 = slice( a, b, index[2].step )
                
            else:
                internal_index2 = np.arange( self._xmin, self._xmax )[ index[2] ]

        else:
            internal_index1 = index[1]
            internal_index2 = index[2]

        # get all data slices and concatenate them
        slices = []
        for file_no in np.unique( valid_steps[:,0] ):
            file = ir.file_hub.open( self._files[file_no] )
            slices.append( file[ self._selected_ext ].data[ valid_steps[ valid_steps[:,0] == file_no, 1 ], internal_index1, internal_index2 ] )
        slices = np.vstack( slices )

        # remove first dimension if there is only one slice
        if slices.shape[0] == 1:
            slices = slices[0,:,:]
            
        return slices

    # function to get an image step
    # Note: this method makes use of astropy's section method to directly access
    # the data on-disk without loading all of the data into memory
    # TODO: option to load everything into RAM?
    # TODO: divide by exposure time needs to be in SJI / raster (put warning in docstr)
    def get_image_step( self, step, divide_by_exptime=True ):
        """
        Returns the image at position step. This function uses the section 
        routine of astropy to only return a slice of the image and avoid 
        memory problems.
        
        Parameters
        ----------
        step : int
            Time step in the data cube.

        Returns
        -------
        numpy.ndarray
            2D image at time step <step>. Format: [y,x] (SJI), [y,wavelength] (raster).
        """
        
        # Check whether line and step exist
        if step < 0 or step >= self.n_steps:
            raise ValueError( "This image step does not exist!" )

        # get file number and file step            
        file_no, file_step = self._whereat( step )
        
        # open file
        file = ir.file_hub.open( self._files[file_no] )
        
        # get exposure time 
        
        # get image (cropped if desired)
        if self._cropped:
            return file[self._selected_ext].section[file_step, self._ymin:self._ymax, self._xmin:self._xmax]
        else:
            return file[self._selected_ext].section[file_step, :, :] 

    # crop data cube
    def crop( self ):
        raise NotImplementedError
    
    # some checks that should be run on every single file and not just the first
    def _check_integrity( self, hdu ):
    
        # raster: check whether the selected extension contains the right line
        if hdu[0].header['INSTRUME'] == 'SPEC' and not self._line in hdu[0].header['TDESC{}'.format( self._selected_ext )]:
            raise CorruptFITSException( "{}: This is not the right line".format( hdu._file.name  ) )
            
        # check whether the data part of the selected extension comes with the right dimensions
        if len( hdu[ self._selected_ext ].shape ) != 3:
            raise CorruptFITSException( "{}: The data extension does not contain a three-dimensional data cube!".format( hdu._file.name ) )
                
        # check whether the array with time-specific headers is valid
        if len( hdu[ self._n_ext-2 ].shape ) != 2:
            raise CorruptFITSException( "{}: The time-specific header extension does not contain a two-dimensional data cube!".format( hdu._file.name ) )
        
        # check whether the array with time-specific headers has the right amount of columns, as specified in the header
        keys_to_remove=['XTENSION', 'BITPIX', 'NAXIS', 'NAXIS1', 'NAXIS2', 'PCOUNT', 'GCOUNT']
        header_keys = dict( hdu[ self._n_ext-2 ].header )
        header_keys = {k: v for k, v in header_keys.items() if k not in keys_to_remove}

        if hdu[ self._n_ext-2 ].shape[1] != len( header_keys ):
            raise CorruptFITSException( "{}: Second extension has not the same amount of columns as number of headery keys.".format( hdu._file.name ) )    

    # functions to get, set and reset image bounds
    def _get_bounds( self ):
        return [self._xmin, self._xmax, self._ymin, self._ymax]
    
    def _set_bounds( self, bounds ):
        self._cropped = True
        self._xmin, self._xmax, self._ymin, self._ymax = bounds
        self._ico.set_bounds( bounds )

    def _reset_bounds( self ):
        self._cropped = False
        self._xmin, self._xmax, self._ymin, self._ymax = None, None, None, None
        self._ico.set_bounds( [None, None, None, None] )

    # functions to enter and exit a context
    def __enter__( self ):
        return self

    def __exit__( self ):
        self.close()
        
    # function to convert pixels to coordinates
    def pix2coords( self, step, pixel_coordinates ):
        """
        Returns solar coordinates for the list of given pixel coordinates.
        
        **Caution**: This function takes pixel coordinates in the form [x,y] while
        images come as [y,x]
        
        Parameters
        ----------
        step : int
            The time step in the SJI to get the solar coordinates for. 
        pixel_coordinates : np.array
            Numpy array with shape (pixel_pairs,2) that contains pixel coordinates
            in the format [x,y]
            
        Returns
        -------
        float
            Numpy array with shape (pixel_pairs,2) containing solar coordinates
        """

        return self._ico.pix2coords( step, pixel_coordinates )

    # function to convert coordinates to pixels (wrapper for wcs)
    def coords2pix( self, step, wl_solar_coordinates, round_pixels=True ):
        """
        Returns pixel coordinates for the list of given wavelength in angstrom / solar y coordinates.
        
        Parameters
        ----------
        step : int
            The time step in the SJI to get the pixel coordinates for. 
        wl_solar_coordinates : np.array
            Numpy array with shape (coordinate_pairs,2) that contains wavelength in 
            angstrom / solar y coordinates in the form [lat/lon] in units of arcseconds
            
        Returns
        -------
        float
            Numpy array with shape (coordinate_pairs,2) containing pixel coordinates
        """
        
        return self._ico.coords2pix( step, wl_solar_coordinates, round_pixels=round_pixels )

    # function to get axis coordinates for a particular image
    def get_axis_coordinates( self, step ):
        """
        Returns coordinates for the image at the given time step.
        
        Parameters
        ----------
        step : int
            The time step in the SJI to get the coordinates for.

        Returns
        -------
        float
            List [coordinates along x axis, coordinates along y axis]
        """

        return self._ico.get_axis_coordinates( step, self.shape )
        


            
        
if __name__ == "__main__":


    fits_data1 = iris_data_cube( '/home/chuwyler/Desktop/FITS/20140329_140938_3860258481/iris_l2_20140329_140938_3860258481_SJI_1400_t000.fits' )
    fits_data2 = iris_data_cube( 
           [ "/home/chuwyler/Desktop/IRISreader/irisreader/data/IRIS_raster_test1.fits", 
            "/home/chuwyler/Desktop/IRISreader/irisreader/data/IRIS_raster_test2.fits" ],
            line="Mg"
    )



