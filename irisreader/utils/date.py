#!/usr/bin/env python3

# This file contains date utility functions

from datetime import datetime as dt
from datetime import timedelta

T_FORMAT_MS = '%Y-%m-%dT%H:%M:%S.%f'
T_FORMAT_S = '%Y-%m-%dT%H:%M:%S'


def from_Tformat( date_str ):
    """
    Docstring
    """
    try:
        date = dt.strptime( date_str , T_FORMAT_MS )
    except ValueError:
        date = dt.strptime( date_str , T_FORMAT_S )
    return date

def to_Tformat( date, milliseconds=True ):
    """
    Docstring
    """
    if milliseconds:
        date_str = dt.strftime( date, T_FORMAT_MS )[:-3]
    else: # round to seconds
        microseconds = date.microsecond / 1e6
        date_str = dt.strftime( date + timedelta( seconds=round(microseconds) ) , T_FORMAT_S )
    return date_str

def full_obsid( start_date, obsid ):
    """
    Docstring
    """
    # round seconds accordint go microseconds
    microseconds = start_date.microsecond / 1e6
    return dt.strftime( start_date + timedelta( seconds=round(microseconds) ) , "%Y%m%d_%H%M%S_" + obsid )

def to_epoch( date ):
    """
    Docstring
    """
    return (date - dt.utcfromtimestamp(0)).total_seconds()

