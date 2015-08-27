#!/usr/bin/python2
"""
Michael Hirsch Dec 2014
This program detects aurora in multi-terabyte raw video data files
It is also used for the Haystack passive FM radar ionospheric activity detection
"""
from __future__ import division, absolute_import
from warnings import warn
try:
    import cv2
except ImportError as e:
    exit('This program requires OpenCV2 or OpenCV3 installed into your Python.  {}'.format(e))
print('OpenCV '+str(cv2.__version__)) #some installs of OpenCV don't give a consistent version number, just a build number and I didn't bother to parse this.
#
from pandas import read_excel
from os.path import join,isfile
import numpy as np
from scipy.signal import wiener
from scipy.misc import bytescale
from time import time
#
try:
    from .pyimagevideo.getaviprop import getaviprop
    from .cvops import dooptflow,dothres,dodespeck,domorph,doblob
    from .cvsetup import setupkern,svsetup,svrelease,setupof,setupblob,setupfigs
    from .getpassivefm import getfmradarframe
except:
    from pyimagevideo.getaviprop import getaviprop
    from cvops import dooptflow,dothres,dodespeck,domorph,doblob
    from cvsetup import setupkern,svsetup,svrelease,setupof,setupblob,setupfigs
    from getpassivefm import getfmradarframe
#
from histutils.walktree import walktree
from histutils.rawDMCreader import getDMCparam,getDMCframe,getserialnum

#plot disable
pshow = ('thres','final')
#'raw' #often not useful due to no autoscale
#'rawscaled'      #True  #why not just showfinal
#'hist' ogram
# 'flowvec'
#'flowhsv'
#'thres'
#'ofmag'
#'meanmedian'
#'morph'
#'final'
#'det'
#savedet
complvl = 4 #tradeoff b/w speed and filesize for TIFF

#only import matplotlib if needed to save time
if np.in1d(('det','hist','ofmag','meanmedian','savedet'),pshow).any():
    from matplotlib.pylab import draw, pause, figure, hist

try:
    import h5py
except ImportError as e:
    warn('h5py not working. Wont be able to save detections to disk')
    print(str(e))
    savedet=False

def loopaurorafiles(flist, up, savevideo, framebyframe, verbose):
    if not flist:
        warn('no files specified')
        return

    camser,camparam = getcamparam(up['paramfn'],flist)

    for f,s in zip(flist,camser): #iterate over files in list
        result = procaurora(f,s,camparam,up,savevideo,framebyframe,verbose)

def procaurora(f,s,camparam,up,savevideo,framebyframe,verbose=False):
    tic = time()

    try:
        cp = camparam[s] #pick the parameters for this camara from pandas DataFrame
    except (KeyError,ValueError):
        warn('using first column of '+up['paramfn'] + ' as I didnt find '+str(s)+' in it.')
        cp = camparam.iloc[:,0] #fallback to first column

    finf,ap,dfid = getvidinfo(f,cp,up,verbose)
    if finf is None: return
#%% setup optional video/tiff writing (mainly for debugging or publication)
    svh = svsetup(savevideo,complvl, ap, cp, up,pshow)
#%% setup blob
    blobdetect = setupblob(cp['minblobarea'], cp['maxblobarea'], cp['minblobdist'])
#%% cv opt. flow matrix setup
    uv,lastflow, ofmed, gmm = setupof(ap,cp)
#%% kernel setup
    kern = setupkern(ap,cp)
#%% mag plots setup
    pl = setupfigs(finf,f,pshow)
#%% start main loop
    for ifrm in finf['frameind'][:-1]:
#%% load and filter
        framegray,frameref,ap = getraw(dfid,ifrm,finf,svh,ap,cp,savevideo,verbose)
        if framegray is None: break
#%% compute optical flow or Background/Foreground
        if lastflow is not None: #very fast way to check mode
            flow,ofmaggmm,ofmed,pl = dooptflow(framegray,frameref,lastflow,uv,
                                               ifrm, ap,cp,pl,pshow)
            lastflow = flow.copy() #I didn't check if the .copy() is strictly necessary
        else: #background/foreground
            ofmaggmm = gmm.apply(framegray)
#%% threshold
        thres = dothres(ofmaggmm, ofmed, ap,cp,svh,pshow)
#%% despeckle
        despeck = dodespeck(thres,cp['medfiltsize'],svh,pshow)
#%% morphological ops
        morphed = domorph(despeck,kern,svh,pshow)
#%% blob detection
        final = doblob(morphed,blobdetect,framegray,ifrm,svh,pl,pshow) #lint:ok
#%% plotting in loop
        """
        http://docs.opencv.org/modules/highgui/doc/user_interface.html
        """

        if np.in1d(('det','hist','ofmag','meanmedian'),pshow).any():
            draw(); pause(0.001)

        if not ifrm % 50:
            print('frame {:0d}'.format(ifrm))
            if (framegray == 255).sum() > 40: #arbitrarily allowing up to 40 pixels to be saturated at 255, to allow for bright stars and faint aurora
                print('* Warning: video may be saturated at value 255, missed detections can result')
            if (framegray == 0).sum() > 4:
                print('* Warning: video may be saturated at value 0, missed detections can result')

        if framebyframe: #wait indefinitely for spacebar press
            keypressed = cv2.waitKey(0)
            framebyframe,dobreak = keyhandler(keypressed,framebyframe)
        else:
            keypressed = cv2.waitKey(1)
            framebyframe, dobreak = keyhandler(keypressed,framebyframe)
        if dobreak:
            break
#%% done looping this file
    try:
        if finf['reader'] == 'raw':
            dfid.close()
        elif finf['reader'] == 'cv2':
            dfid.release()
    except Exception as e:
        print(str(e))

    print('{:0.1f}'.format(time()-tic) + ' seconds to process ' + f)
    if 'savedet' in pshow:
        detfn = join(up['outdir'],f +'_detections.h5')
        detpltfn = join(up['outdir'],f +'_detections.png')
        if isfile(detfn):
            warn('overwriting existing ' + detfn)

        try:
            print('saving detections to ' + detfn)
            with h5py.File(detfn,'w',libver='latest') as h5fid:
                h5fid["/det"] = pl['detect']
            print('saving detection plot to ' + detpltfn)
            pl['fdet'].savefig(detpltfn,dpi=100,bbox_inches='tight')
        except Exception as e:
            warn('trouble saving detection result   '.format(e))

    svrelease(svh,savevideo)
    return pl


def keyhandler(keypressed,framebyframe):
    if keypressed == -1: # no key pressed
        return (framebyframe,False)
    elif keypressed == 1048608: #space
        return (not framebyframe, False)
    elif keypressed == 1048603: #escape
        return (None, True)
    else:
        print('keypress code: ' + str(keypressed))
        return (framebyframe,False)


def getraw(dfid,ifrm,finf,svh,ap,cp,savevideo,verbose):
    """ this function reads the reference frame too--which makes sense if youre
       only reading every Nth frame from the multi-TB file instead of every frame
    """
    frameref = None #just in case not used
    dowiener = np.isfinite(cp['wienernhood'])
#%% reference frame

    if finf['reader'] == 'raw' and dfid is not None:
        if ap['twoframe']:
            frameref = getDMCframe(dfid,ifrm,finf,verbose)[0]
            frameref = bytescale(frameref, ap['rawlim'][0], ap['rawlim'][1])
            if dowiener:
                frameref = wiener(frameref,cp['wienernhood'])

        frame16,rfi = getDMCframe(dfid,ifrm+1,finf)
        if frame16 is None or rfi is None: #FIXME accidental end of file, smarter way to detect beforehand?
            ap['rawframeind'] = np.delete(ap['rawframeind'], np.s_[ifrm:])
            return None, None, ap
        framegray = bytescale(frame16, ap['rawlim'][0], ap['rawlim'][1])

    elif finf['reader'] == 'cv2':
        if ap['twoframe']:
            retval,frameref = dfid.read()
            if not retval:
                if ifrm==0:
                    warn('could not read video file, sorry')
                print('done reading video.')
                return None, None, ap
            if frameref.ndim>2:
                frameref = cv2.cvtColor(frameref, cv2.COLOR_RGB2GRAY)
            if dowiener:
                frameref = wiener(frameref,cp['wienernhood'])

        retval,frame16 = dfid.read() #TODO this is skipping every other frame!
        # TODO can we use dfid.set(cv.CV_CAP_PROP_POS_FRAMES,ifrm) to set 0-based index of next frame?
        rfi = ifrm
        if not retval:
            warn('could not read video from file!')
            return None, None, ap
        if frame16.ndim>2:
            framegray = cv2.cvtColor(frame16, cv2.COLOR_RGB2GRAY)
        else:
            framegray = frame16 #copy NOT needed
    elif finf['reader'] == 'h5':   #one frame per file
        if ap['twoframe']:
            frameref = getfmradarframe(dfid[ifrm])[2]
            frameref = bytescale(frameref, ap['rawlim'][0], ap['rawlim'][1])
        frame16 = getfmradarframe(dfid[ifrm+1])[2]
        rfi = ifrm
        framegray = bytescale(frame16, ap['rawlim'][0], ap['rawlim'][1])


#%% current frame
    ap['rawframeind'][ifrm] = rfi

    if dowiener:
        framegray = wiener(framegray,cp['wienernhood'])

    if 'raw' in pshow:
        # cv2.imshow just divides by 256, NOT autoscaled!
        # http://docs.opencv.org/modules/highgui/doc/user_interface.html
        cv2.imshow('video', framegray)
#%% plotting
    if 'rawscaled' in pshow:
        cv2.imshow('raw video, scaled to 8-bit', framegray)
    # image histograms (to help verify proper scaling to uint8)
    if 'hist' in pshow:
        figure(321).clf()
        ax=figure(321).gca()
        hist(frame16.flatten(), bins=128, fc='w',ec='k', log=True)
        ax.set_title('raw uint16 values')

        figure(322).clf()
        ax=figure(322).gca()
        hist(framegray.flatten(), bins=128, fc='w',ec='k', log=True)
        ax.set_xlim((0,255))
        ax.set_title('normalized video into opt flow')

    if svh['video'] is not None:
        if savevideo == 'tif':
            svh['video'].save(framegray,compress=complvl)
        elif savevideo == 'vid':
            svh['video'].write(framegray)

    return framegray,frameref,ap

def getvidinfo(fn,cp,up,verbose):
    print('using {} for {}'.format(cp['ofmethod'],fn))
    if verbose:
        print('minBlob='+str(cp['minblobarea']) + ' maxBlob='+
          str(cp['maxblobarea']) + ' maxNblob=' + str(cp['maxblobcount']) )

    if fn.endswith('.DMCdata'):
        xypix=(cp['xpix'],cp['ypix'])
        xybin=(cp['xbin'],cp['ybin'])
        if up['startstop'][0] is None:
            finf = getDMCparam(fn,xypix,xybin,up['framestep'],verbose)
        else:
            finf = getDMCparam(fn,xypix,xybin,
                     (up['startstop'][0], up['startstop'][1], up['framestep']))
        finf['reader']='raw'

        dfid = open(fn,'rb') #I didn't use the "with open(f) as ... " because I want to swap in other file readers per user choice

    elif fn.lower().endswith(('.h5','.hdf5')):
        finf = {'reader':'h5'}
        print('attempting to read HDF5 {}'.format(fn))
        dfid = flist
        finf['nframe'] = len(dfid) # currently the passive radar uses one file per frame

        range_km,vel_mps = getfmradarframe(fn)[:2] #assuming all frames are the same size
        finf['superx'] = range_km.size
        finf['supery'] = vel_mps.size
        finf['frameind'] = np.arange(finf['nframe'],dtype=np.int64)
    else:
        #FIXME start,stop,step is not yet implemented, simply uses every other frame
        print('attempting to read {} with OpenCV.'.format(fn))
        finf = {'reader':'cv2'}

        dfid = cv2.VideoCapture(fn)
        nframe,xpix,ypix,fps,codec=getaviprop(dfid)



        if nframe<1 or xpix<1 or ypix<1:
            warn('I may not be reading {} correctly, trying anyway by reading an initial frame..'.format(fn))
            retval, frame =dfid.read()
            if not retval:
                warn('could not succeed in any way to read '+str(fn))
                return None, None, None
            ypix,xpix = frame.shape
            finf['nframe'] = 100000 #FIXME guessing how many frames in file
        else:
            finf['nframe'] = nframe
        finf['superx'] = xpix
        finf['supery'] = ypix

        finf['frameind']=np.arange(finf['nframe'],dtype=np.int64)


#%% extract analysis parameters
    ap = {'twoframe':bool(cp['twoframe']), # note this should be 1 or 0 input, not the word, because even the word 'False' will be bool()-> True!
          'ofmethod':cp['ofmethod'].lower(),
          'rawframeind': np.empty(finf['nframe'],np.int64), #int64 for very large files on Windows Python 2.7, long is not available on Python3
          'rawlim': (cp['cmin'], cp['cmax']),
          'xpix': finf['superx'], 'ypix':finf['supery'],
          'thresmode':cp['thresholdmode'].lower()}

    return finf, ap, dfid

def getcamparam(paramfn,flist):
    #uses pandas and xlrd to parse the spreadsheet parameters
    if flist[0].endswith('.DMCdata'):
        camser = getserialnum(flist)
    else:
        #FIXME add your own criteria to pick which spreadsheet paramete column to use.
        # for now I tell it to just use the first column (same criteria for all files)
        warn('using first column of spreadsheet only for camera parameters')
        camser = [None] * len(flist)

    camparam = read_excel(paramfn,index_col=0,header=0) #returns a nicely indexable DataFrame
    return camser, camparam

if __name__=='__main__':
    from argparse import ArgumentParser
    p = ArgumentParser(description='detects aurora in raw video files')
    p.add_argument('indir',help='specify file, OR top directory over which to recursively find video files',type=str,nargs='+')
    p.add_argument('-e','--vidext',help='extension of raw video file',type=str,default='DMCdata')
    p.add_argument('--fps',help='output file FPS (note VLC needs fps>=3)',type=float,default=3)
    p.add_argument('-p','--framebyframe',help='space bar toggles play/pause', action='store_true')
    p.add_argument('-s','--savevideo',help='save video at each step (can make enormous files)',action='store_true')
    p.add_argument('-t','--savetiff',help='save tiff at each step (can make enormous files)',action='store_true')
    p.add_argument('-k','--step',help='frame step skip increment (default 10000)',type=int,default=1)
    p.add_argument('-f','--frames',help='start stop frames (default all)',type=int,nargs=2,default=(None,None))
    p.add_argument('-o','--outdir',help='directory to put output files in',type=str,default='') #None doesn't work with Windows
    p.add_argument('--ms',help='keogram/montage step [1000] dont make it too small like 1 or output is as big as original file!',type=int,default=1000)
    p.add_argument('-c','--contrast',help='[low high] data numbers to bound video contrast',type=int,nargs=2,default=(None,None))
    p.add_argument('--rejectvid',help='reject raw video files with less than this many frames',type=int,default=10)
    p.add_argument('-r','--rejectdet',help='reject files that have fewer than this many detections',type=int,default=10)
    p.add_argument('--paramfn',help='parameter file for cameras',type=str,default='camparam.xlsx')
    p.add_argument('-v','--verbose',help='verbosity',action='store_true')
    p.add_argument('--profile',help='profile debug',action='store_true')
    a = p.parse_args()

    uparams = {'rejvid':a.rejectvid,
              'framestep':a.step,
              'startstop':a.frames,
              'montstep':a.ms,'clim':a.contrast,
              'paramfn':a.paramfn,'rejdet':a.rejectdet,'outdir':a.outdir,
              'fps':a.fps
              }

    if a.savetiff:
        savevideo='tif'
    elif a.savevideo:
        savevideo='vid'
    else:
        savevideo=''
#%% run program (allowing ctrl+c to exit)
    try:
        #note, if a specific file is given, vidext is ignored
        flist = walktree(a.indir,'*.' + a.vidext)
        if a.profile:
            import cProfile,pstats
            profFN = 'profstats.pstats'
            cProfile.run('main(flist, uparams, savevideo, a.framebyframe, a.verbose)',profFN)
            pstats.Stats(profFN).sort_stats('time','cumulative').print_stats(50)
        else:
            loopaurorafiles(flist, uparams, savevideo, a.framebyframe, a.verbose)
            #show()
    except KeyboardInterrupt:
        exit('aborting per user request')