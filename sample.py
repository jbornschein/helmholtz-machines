#!/usr/bin/env python 

from __future__ import print_function, division

import sys
sys.path.append("..")
sys.setrecursionlimit(100000)

import os
import logging

import numpy as np
import cPickle as pickle

import theano
import theano.tensor as tensor

from PIL import Image
from argparse import ArgumentParser
from progressbar import ProgressBar

from blocks.main_loop import MainLoop

from helmholtz.gmm import GMM
from helmholtz.rws import ReweightedWakeSleep
from helmholtz.prob_layers import replicate_batch, logsumexp

logger = logging.getLogger("sample.py")

FORMAT = '[%(asctime)s] %(name)-15s %(message)s'
DATEFMT = "%H:%M:%S"
logging.basicConfig(format=FORMAT, datefmt=DATEFMT, level=logging.INFO)

def scale_norm(arr):
    arr = arr - arr.min()
    scale = (arr.max() - arr.min())
    return scale * arr

def img_grid(arr, global_scale=True):
    N, height, width = arr.shape

    rows = int(np.sqrt(N))
    cols = int(np.sqrt(N))

    if rows*cols < N:
        cols = cols + 1

    if rows*cols < N:
        rows = rows + 1

    total_height = rows * (height+1)
    total_width  = cols * (width+1)

    if global_scale:
        arr = scale_norm(arr)

    I = np.zeros((total_height, total_width))

    for i in xrange(N):
        r = i // cols
        c = i % cols

        if global_scale:
            this = arr[i]
        else:
            this = scale_norm(arr[i])

        offset_y, offset_x = r*(height+1), c*(width+1)
        I[offset_y:(offset_y+height), offset_x:(offset_x+width)] = this
    
    I = (255*I).astype(np.uint8)
    return Image.fromarray(I)

#-----------------------------------------------------------------------------

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--expected", "-e", action="store_true",
            help="Display expected output from last layer")
    parser.add_argument("--nsamples", "--samples", "-s", type=int, 
            default=100, help="no. of samples to draw")
    parser.add_argument("--oversample", "--oversamples", type=int, 
            default=1000)
    parser.add_argument("--ninner", type=int, 
            default=100, help="no. of q(x) samples to draw")
    parser.add_argument("--shape", type=str, default=None,
            help="shape of output samples")
    parser.add_argument("experiment", help="Experiment to load")
    args = parser.parse_args()

    logger.info("Loading model %s..." % args.experiment)
    with open(args.experiment, "rb") as f:
        m = pickle.load(f)

    if isinstance(m, MainLoop):
        m = m.model

    brick = m.get_top_bricks()[0]
    while len(brick.parents) > 0:
        brick = brick.parents[0]

    assert isinstance(brick, (ReweightedWakeSleep, GMM))

    if args.shape is not None:
        img_shape = [int(i) for i in args.shape.split(',')]
    else:
        p0 = brick.p_layers[0]
        sqrt = int(np.sqrt(p0.dim_X))
        img_shape = [sqrt, sqrt]

    logger.info("Compiling function...")

    #----------------------------------------------------------------------
    # Compile functions

    n_samples = tensor.iscalar('n_samples')
    oversample = tensor.iscalar('n_samples')

    samples, log_w = brick.sample(n_samples, oversample=oversample, n_inner=args.ninner)

    if args.expected:
        # Ok, take the second last and sample expected
        x = brick.p_layers[0].sample_expected(samples[1])
    else:
        x = samples[0]

    x = x.reshape([n_samples]+img_shape)

    do_sample = theano.function(
                        [n_samples, oversample], 
                        [x, log_w],
                        name="do_sample", allow_input_downcast=True)

    #----------------------------------------------------------------------

    n_samples = tensor.iscalar('n_samples')

    samples, _, _ = brick.sample_p(n_samples)

    if args.expected:
        # Ok, take the second last and sample expected
        x_p = brick.p_layers[0].sample_expected(samples[1])
    else:
        x_p = samples[0]

    x_p = x_p.reshape([n_samples]+img_shape)

    do_sample_p = theano.function(
                        [n_samples], 
                        x_p,
                        name="do_sample_p", allow_input_downcast=True)

    #----------------------------------------------------------------------
    logger.info("Sample from model...")

    n_layers = len(brick.p_layers)
    n_samples = args.nsamples

    x = [None] * n_samples
    log_w = [None] * n_samples
    progress = ProgressBar()
    for n in progress(xrange(n_samples)):
        x[n], log_w[n] = do_sample(1, args.oversample)
     
    x = np.concatenate(x)
    img = img_grid(x, global_scale=True)

    fname = os.path.splitext(args.experiment)[0]
    fname += "-samples.png"

    logger.info("Saving %s ..." % fname)
    img.save(fname)

    #----------------------------------------------------------------------
    logger.info("Sample from p(x, h) ...")
    
    x_p = do_sample_p(n_samples)
    img_p = img_grid(x_p, global_scale=True)

    fname = os.path.splitext(args.experiment)[0]
    fname += "-psamples.png"

    logger.info("Saving %s ..." % fname)
    img_p.save(fname)
    

    if args.show:
        import pylab

        pylab.figure()
        pylab.gray()
        pylab.axis('off')
        pylab.imshow(img, interpolation='nearest')

        pylab.figure()
        pylab.gray()
        pylab.axis('off')
        pylab.imshow(img_p, interpolation='nearest')
 
        pylab.show(block=True)