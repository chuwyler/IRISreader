#!/usr/bin/env python3

"""
sji_cube class: abstraction that makes the data, the headers and a number
of auxiliary variables available for IRIS slit-jaw image data
"""

import numpy as np
import matplotlib.pyplot as plt

from irisreader import iris_data_cube

# import configuration
from irisreader.config import DEBUG

class sji_cube( iris_data_cube ):
    """
    This class implements an abstraction of an IRIS SJI FITS file.
    
    Parameters
    ----------
    filename : string
        Path to the IRIS SJI FITS file.
    keep_null : boolean
        Controls whether images that are NULL (-200) everywhere are removed from the data cube. keep_null=True keeps NULL images and keep_null=False removes them.
        
        
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
        Endt date of the selected observation.
    mode : str
        Observation mode of the selected observation ('sit-and-stare' or 'raster').
    line_info : str
        Description of the selected line.
    n_steps : int
        Number of time steps in the data cube.
    primary_headers : dict
        Dictionary with primary headers of the FITS file (lazy loaded).
    time_specific_headers : dict
        List of dictionaries with time-specific headers of the selected line (lazy loaded).
    headers : dict
       List of combined primary and time-specific headers (lazy loaded).
    """


    # constructor
    def __init__( self, file, keep_null=False ):
        
        # call constructor of parent iris_data_cube
        super().__init__( file, line='', keep_null=keep_null )        
        
        # raise error if the data_cube is a raster
        if self.type=='raster':
            self.close()
            raise ValueError("This is a raster file. Please use raster_cube to open it.")
            
        # line specific headers are not required - delete instance variable
        del self.line_specific_headers
    
    # return description upon a print call
    def __repr__( self ):
        return "SJI {} line window:\n(n_steps, n_y, n_x) = {}".format( self.line_info, self.shape )

    # function to prepare combined headers
    def _prepare_combined_headers( self ):
        """
        Prepares the combination (primary header, time-specific header) lazily
        for each image.
        """
        if DEBUG: print( "Lazy loading combined headers" )
        self.headers = [dict(list(self.primary_headers.items())+list(t_header.items())) for t_header in self.time_specific_headers]
        
        # manual adjustments
        for i in range(0, self.n_steps):
            self.headers[i]['XCEN'] = self.headers[i]['XCENIX']
            self.headers[i]['YCEN'] = self.headers[i]['YCENIX']
            self.headers[i]['PC1_1'] = self.headers[i]['PC1_1IX']
            self.headers[i]['PC1_2'] = self.headers[i]['PC1_2IX']
            self.headers[i]['PC2_1'] = self.headers[i]['PC2_1IX']
            self.headers[i]['PC2_2'] = self.headers[i]['PC2_2IX']
            self.headers[i]['CRVAL1'] = self.headers[i]['XCENIX']
            self.headers[i]['CRVAL2'] = self.headers[i]['YCENIX']
            self.headers[i]['EXPTIME'] = self.headers[i]['EXPTIMES']

    # overwrite get_image_step function to be able to divide by exposure time
    def get_image_step( self, step, divide_by_exptime=True ):
        """
        Returns the image at position step. This function uses the section 
        routine of astropy to only return a slice of the image and avoid 
        memory problems.
        
        Parameters
        ----------
        step : int
            Time step in the data cube.
        divide_by_exptime : bool
            Whether to divide image by its exposure time or not. Dividing by exposure
            time will present a normalized image instead of the usual data numbers.

        Returns
        -------
        numpy.ndarray
            2D image at time step <step>. Format: [y,x].
        """ 
        # get exposure time stored in 'EXPTIMES'
        exptime = self.time_specific_headers[ step ]['EXPTIMES']
        
        # divide image by exposure time
        image = super().get_image_step( step ) 
        image[image>0] /= exptime
        return image
            
    # function to plot an image step
    def plot( self, step, units='pixels', gamma=None, cutoff_percentile=99.9 ):
        """
        Plots the slit-jaw image at time step <step>. 
        
        Parameters
        ----------
        step : int
            The time step in the SJI.
        units : str
            Tick units: 'pixels' for indices in the array or 'coordinates' for units in arcseconds on the sun.
        gamma : float
            Gamma exponent for gamma correction that adjusts the plot scale. If gamma is None (default),
            gamma=1 is used for the photospheric SJI 2832 and gamma=0.4 otherwise.
        cutoff_percentile : float
            Often the maximum pixels shine out everything else, even after gamma correction. In order to reduce 
            this effect, the percentile at which to cut the intensity off can be specified with cutoff_percentile
            in a range between 0 and 100.
        """

        # if gamma is not specified, use gamma=1 for SJI_2832 and gamma=0.4 for everything else
        if gamma is None:
            if 'Mg II wing 2832' in self.line_info: # photospheric line
                gamma = 1
            else:
                gamma = 0.4

        # load image into memory and exponentiate it with power
        image = self.get_image_step( step, divide_by_exptime=True ).clip( min=0 ) ** gamma
        vmax = np.percentile( image, cutoff_percentile )
    
        # set image extent and labels according to choice of units
        ax = plt.subplot(111)
        
        if units == 'coordinates':
            units = self.get_axis_coordinates( step=step )
            extent = [ units[0][0], units[0][-1], units[1][0], units[1][-1]  ]
            ax.set_xlabel( self._ico.xlabel )
            ax.set_ylabel( self._ico.ylabel )

        elif units == 'pixels':
            extent = [ 0, image.shape[1], 0, image.shape[0] ]
            ax.set_xlabel("camera x")
            ax.set_ylabel("camera y")
            
        else:
            raise ValueError( "Plot units '" + units + "' not defined!" )
            
        # create title (TODO)
        ax.set_title(self.line_info + '\n' + self.time_specific_headers[step]['DATE_OBS'] )

        # show image
        ax.imshow( image, cmap='gist_heat', origin='lower', vmax=vmax, extent=extent )
        
        # set aspect ratio depending
        ax.set_aspect('equal') 
        
        # show plot
        plt.show()
        
        # delete image variable (otherwise memory mapping keeps file open)
        del image

    # function to get slit position (taking into account cropping)
    def get_slit_pos( self, step ):
        """
        Returns position of the slit in pixels (takes into account cropping).
        
        Parameters
        ----------
        step : int
            Time step in the data cube.

        Returns
        -------
        slit_position : int
            Slit position in pixels
        """
        pos = self.time_specific_headers[ step ]['SLTPX1IX']
        if self._cropped:
            return pos - self._xmin
        else:
            return pos

# Test code
if __name__ == "__main__":
    
    sji = sji_cube( '/home/chuwyler/Desktop/FITS/20140910_112825_3860259453/iris_l2_20140910_112825_3860259453_SJI_1400_t000.fits' )
    very_large_sji = iris_data_cube( "/home/chuwyler/Desktop/FITS/20140420_223915_3864255603/iris_l2_20140420_223915_3864255603_SJI_1400_t000.fits" )

    sji.plot(0)
    sji.crop()
    sji.plot(0)
