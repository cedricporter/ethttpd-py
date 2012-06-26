#!/usr/bin/env python
# author:  Hua Liang [ Stupid ET ]
# email:   et@everet.org
# website: http://EverET.org
#

import pprint

def printargs(f):
    'A decorator to wrap f, and printing arguments of f'
    def printer(*args, **kwds):
        print 'Function:', f.func_name
        pprint.pprint(args)
        f(*args, **kwds)
    return printer
