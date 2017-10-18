#!/usr/bin/env python
"""
batch processing of entire directories of images (one directory per night typically)
does NOT automatically delete original data

Steps
0) create list of directories to process
1) create index of randomly ordered filenames, opening each one to determine its relative elapsed time, creating index.h5
2) detect auroral events of interest, store their indices


NOTE: str() in cmd is a workaround for Windows deficiency--don't remove unless you know the Python Windows bug is fixed!
"""
import sys
from pathlib import Path
import subprocess
#
CONF = 'dmc2017.ini'
INDEXFN = 'spool/index.h5'

def write_index(d:Path, codedir:Path):
    """
    create spool/index.h5
    """
    cmd = ['python','FileTick.py',
           str(d/'spool'), str(d/INDEXFN),
           '-s1296', '-z0']

    print(cmd)

    ret = subprocess.run(cmd, cwd=codedir/'dmcutils')
    return ret.returncode


def detect_aurora(d:Path, outdir:Path, codedir:Path):
    cmd = ['python','Detect.py',
           str(d/INDEXFN), str(outdir/d.stem),
           CONF,'-k10']

    print(cmd)

    ret = subprocess.run(cmd, cwd=codedir/'cv_ionosphere')
    return ret.returncode


def extract_aurora(d:Path, outdir:Path, codedir:Path):
    cmd = ['python','ConvertSpool2h5.py',
           str(d/INDEXFN),
       '-det', str(outdir/d.stem/'auroraldet.h5'),
       '-o', str(outdir/d.stem/(d.stem+'extracted.h5')),
       '-z0']

    print(cmd)

    ret = subprocess.run(cmd, cwd=codedir/'dmcutils')
    return ret.returncode


def preview_extract(d:Path, outdir:Path, codedir:Path):
    cmd = ['python','Convert_HDF5_to_AVI.py',
           str(outdir/d.stem/(d.stem+'extracted.h5')),
           str(outdir/d.stem/(d.stem+'extracted.avi'))]

    print(cmd)

    ret = subprocess.run(cmd, cwd=codedir/'pyimagevideo')
    return ret.returncode


if __name__ == '__main__':

    from argparse import ArgumentParser
    p = ArgumentParser()
    p.add_argument('indir',help='directory containing directories to process (top level directory)')
    p.add_argument('outdir',help='directory to place index, extracted frames and AVI preview')
    p.add_argument('-codepath',help='top level directory where Git repos are stored',default='~/code')
    p = p.parse_args()

    codedir = Path(p.codepath).expanduser()
    indir = Path(p.indir).expanduser()
    outdir = Path(p.outdir).expanduser()
    print('using',sys.executable,'in',indir,'with',codedir,'extracting to',outdir)
# %% 0) find directories of data
    dlist = [x for x in indir.iterdir() if (x/'spool').is_dir()]

    for d in dlist:
# %% 1) create spool/index.h5
        ret = write_index(d, codedir)
        #if ret != 0: continue
# %% 2) detect aurora
        ret = detect_aurora(d, outdir, codedir)
        #if ret != 0: continue
# %% 3) extract auroral data
        ret = extract_aurora(d, outdir, codedir)
        #if ret != 0: continue
# %% 4) create AVI preview of extracted data
        ret = preview_extract(d, outdir, codedir)
        #if ret != 0: continue