#!/usr/bin/env python3

# This file contains coordinate conversion functions

import numpy as np
import warnings
from astropy.wcs import WCS

# some unit conversions
UNIT_M_NM = 1e10
UNIT_DEC_ARCSEC = 3600
XLABEL_ARCSEC = "solar x [arcsec]"
YLABEL_ARCSEC = "solar y [arcsec]"
XLABEL_ANGSTROM = r'$\lambda$ [$\AA$]'

class iris_coordinates:
    """
    header: header of the selected extension
    """
    
    # constructor
    def __init__( self, header, mode, bounds=[None,None,None,None] ):
                
        # initialize astropy WCS object and suppress warnings
        # set CDELT3 to a tiny value if zero (otherwise wcs produces singular PC matrix)
        # see e.g. discussion at https://github.com/sunpy/irispy/issues/78
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if header['CDELT3'] == 0:
                header['CDELT3'] = 1e-10
                self.wcs = WCS( header )
                header['CDELT3'] = 0
            else:
                self.wcs = WCS( header )
        
        # set mode (sji or raster) and appropriate conversions and labels
        if mode == 'sji':
            self.conversion_factor = [UNIT_DEC_ARCSEC, UNIT_DEC_ARCSEC]
            self.xlabel = XLABEL_ARCSEC
            self.ylabel = YLABEL_ARCSEC
        elif mode == 'raster':
            self.conversion_factor = [UNIT_M_NM, UNIT_DEC_ARCSEC]
            self.xlabel = XLABEL_ANGSTROM
            self.ylabel = YLABEL_ARCSEC
        else:
            raise ValueError( "mode should be either 'sji' or 'raster'" )
        
        self.mode = mode
        
        # set bounds
        self.xmin, self.xmax, self.ymin, self.ymax = bounds
        if self.xmin is None or self.xmax is None or self.ymin is None or self.ymax is None:
            self.cropped = False
        else:
            self.cropped = True
    
    # function to set bounds
    def set_bounds( self, bounds ):
        self.bounds = bounds
    
    # function to convert from camera (pixel) coordinates to solar/physical coordinates
    # wraps astropy.wcs
    def pix2coords( self, timestep, pixel_coordinates ):
        
            # make sure pixel_coordinates is a numpy array
            pixel_coordinates = np.array( pixel_coordinates )
        
            # check dimensions
            ndim = pixel_coordinates.ndim
            shape = pixel_coordinates.shape
            if not ( (ndim == 1 and shape[0] == 2) or (ndim == 2 and shape[1] == 2) ):
                raise ValueError( "pixel_coordinates should be a numpy array with shape (:,2)." ) 
            
            # create a copy of the input coordinates
            pixel_coordinates = pixel_coordinates.copy()
            
            # generalize for single pixel pairs
            if ndim == 1:
                pixel_coordinates = np.array([pixel_coordinates])
                
            # add offset if image is cropped
            if self.cropped:
                pixel_coordinates += np.array([self.xmin, self.ymin])            
            
            # stack timestep to pixels
            pixel_coordinates = np.hstack( [ pixel_coordinates, pixel_coordinates.shape[0]*[[timestep]] ] )
             
            # transform pixels to solar coordinates
            solar_coordinates = self.wcs.all_pix2world( pixel_coordinates, 1 )[:,:2]  
            
            # convert units
            solar_coordinates *= self.conversion_factor
            
            # return tuple if input was only one tuple
            if ndim == 1:
                return solar_coordinates[0]
            else:
                return solar_coordinates
            
    # function to convert from solar/physical coordinates to camera (pixel) coordinates
    # wraps astropy.wcs
    def coords2pix( self, timestep, solar_coordinates, round_pixels=True ):
        
            # make sure solar_coordinates is a numpy array
            solar_coordinates = np.array( solar_coordinates )
        
            # check dimensions
            ndim = solar_coordinates.ndim
            shape = solar_coordinates.shape
            if not ( (ndim == 1 and shape[0] == 2) or (ndim == 2 and shape[1] == 2) ):
                raise ValueError( "pixel_coordinates should be a numpy array with shape (:,2)." ) 
            
            # create a copy of the input coordinates
            solar_coordinates = solar_coordinates.copy()
            
            # generalize for single pixel pairs
            if ndim == 1:
                solar_coordinates = np.array([solar_coordinates])
    
            # convert units
            solar_coordinates = solar_coordinates / self.conversion_factor
                    
            # convert timestep to time coordinate (want always to reference time with timestep)
            time_coordinate = self.wcs.all_pix2world( [[0,0,timestep]], 1  )[0, 2]
    
            # stack timestep to pixels
            solar_coordinates = np.hstack( [ solar_coordinates, solar_coordinates.shape[0]*[[time_coordinate]] ] )
             
            # transform solar coordinates to pixels
            pixel_coordinates = self.wcs.all_world2pix( solar_coordinates, 1 )[:,:2]  
            
            # subtract offset if image is cropped
            if self.cropped:
                pixel_coordinates -= np.array([self.xmin, self.ymin])
                
            # round to nearest pixels            
            if round_pixels:
                pixel_coordinates = np.round( pixel_coordinates ).astype( np.int )
            
            # return tuple if input was only one tuple
            if ndim == 1:
                return pixel_coordinates[0]
            else:
                return pixel_coordinates
                    
    # function to get axis coordinates for a particular image
    def get_axis_coordinates( self, step, shape ):
        
        # create input for wcs.all_pix2world: list of triples (x,y,t)
        # evaluated only at coordinate axes (to be fast)
        arr_x = [[x,0,step] for x in range(shape[2])]
        arr_y = [[0,y,step] for y in range(shape[1])]
            
        # pass pixel lists to wcs.all_pix2world and extract axis values
        # convert from degrees to arcseconds by multiplying with 3600
        coords_x = self.wcs.all_pix2world( arr_x, 1 )[:,0] * self.conversion_factor[0]
        coords_y = self.wcs.all_pix2world( arr_y, 1 )[:,1] * self.conversion_factor[1]
            
        # Return bounded units if image is cropped
        if self.cropped:
            return [ coords_x[self.xmin:self.xmax], coords_y[self.ymin:self.ymax] ]
        else:
            return [ coords_x, coords_y ]    

# Tests: should be sent to unit testing
if __name__ == "__main__":
    from irisreader import observation
    obs = observation("/home/chuwyler/Desktop/FITS/20140910_112825_3860259453/")
    obs.sji[0].plot( 0, units="coordinates" )
    obs.raster["Mg"].plot( 0 )
    obs.raster["Mg"].plot( 0, units="coordinates" )   
    
    # SJI tests:
    conversion = [UNIT_DEC_ARCSEC,UNIT_DEC_ARCSEC]
    shape = obs.sji[0].shape
    xcen = obs.sji[0].primary_headers['XCEN']
    ycen = obs.sji[0].primary_headers['YCEN']

    # back and forth / forth and back
    coords2pix( obs.sji[0]._wcs, 0, pix2coords( obs.sji[0]._wcs, 0, np.array([0,0]), conversion ), conversion ) == np.array([0,0])        
    coords2pix( obs.sji[0]._wcs, 0, pix2coords( obs.sji[0]._wcs, 0, np.array([shape[2],shape[1]]), conversion ), conversion ) == np.array([shape[2],shape[1]])        
    np.linalg.norm( pix2coords( obs.sji[0]._wcs, 0, coords2pix( obs.sji[0]._wcs, 0, np.array([xcen,ycen]), conversion, round_pixels=False ), conversion ) - np.array([xcen,ycen]) ) < 1e10       
    
    # crop
    obs.sji[0].crop()
    coords2pix( obs.sji[0]._wcs, 0, pix2coords( obs.sji[0]._wcs, 0, np.array([0,0]), conversion, xmin=obs.sji[0]._xmin, ymin=obs.sji[0]._ymin ), conversion, xmin=obs.sji[0]._xmin, ymin=obs.sji[0]._ymin )  == np.array([0,0])
    
    # raster tests:
    conversion = [UNIT_M_NM, UNIT_DEC_ARCSEC]
    shape = obs.raster("Mg").shape
    xcen = obs.raster("Mg").primary_headers['XCEN']
    ycen = obs.raster("Mg").primary_headers['YCEN']

    # back and forth / forth and back
    coords2pix( obs.raster["Mg"]._wcs, 0, pix2coords( obs.raster["Mg"]._wcs, 0, np.array([0,0]), conversion ), conversion ) == np.array([0,0])
    coords2pix( obs.raster["Mg"]._wcs, 0, pix2coords( obs.raster["Mg"]._wcs, 0, np.array([shape[2],shape[1]]), conversion ), conversion ) == np.array([shape[2],shape[1]])
    np.linalg.norm( pix2coords( obs.raster("Mg")._wcs, 0, coords2pix( obs.raster("Mg")._wcs, 0, np.array([xcen,ycen]), conversion, round_pixels=False ), conversion ) - np.array([xcen,ycen]) ) < 1e10       

    # crop
    obs.raster("Mg").crop()
    coords2pix( obs.raster("Mg")._wcs, 0, pix2coords( obs.raster("Mg")._wcs, 0, np.array([0,0]), conversion, xmin=obs.raster("Mg")._xmin, ymin=obs.raster("Mg")._ymin ), conversion, xmin=obs.raster("Mg")._xmin, ymin=obs.raster("Mg")._ymin )  == np.array([0,0])
    
    
    
    # get axis
    obs.sji[0].plot(0, units="coordinates")
    axes_coords = get_axis_coordinates( obs.sji[0]._wcs, 0, obs.sji[0].shape, [UNIT_DEC_ARCSEC, UNIT_DEC_ARCSEC] )    
    [ np.min(axes_coords[0]), np.max(axes_coords[0]) ]
    [ np.min(axes_coords[1]), np.max(axes_coords[1]) ]

    obs.raster["Mg"].plot(0, units="coordinates")
    axes_coords = get_axis_coordinates( obs.raster["Mg"]._wcs, 0, obs.raster["Mg"].shape, [UNIT_M_NM, UNIT_DEC_ARCSEC] )    
    [ np.min(axes_coords[0]), np.max(axes_coords[0]) ]
    [ np.min(axes_coords[1]), np.max(axes_coords[1]) ]
