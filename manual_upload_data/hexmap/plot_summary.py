import os, sys, glob
import re
from datetime import datetime
import pandas as pd
import numpy as np
from argparse import ArgumentParser, BooleanOptionalAction
import math
import yaml
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import RegularPolygon, Rectangle
from matplotlib.collections import PatchCollection
from matplotlib.legend_handler import HandlerPatch
from matplotlib.ticker import (MultipleLocator, AutoMinorLocator)
import traceback

try:
    from hexaboard_geometries import *
except ModuleNotFoundError:
    from hexmap.hexaboard_geometries import *

mpl.rcParams.update(mpl.rcParamsDefault)
font = {"size": 20}
mpl.rc("font", **font)

import yaml
configuration = {}
try:
    with open('configuration.yaml', 'r') as file:
        configuration = yaml.safe_load(file)
except FileNotFoundError:
    with open('../configuration.yaml', 'r') as file:
        configuration = yaml.safe_load(file)
        
# different versions of uproot for each OS =.=
if configuration['TestingPCOpSys'] == 'Centos7':
    import uproot3 as uproot
elif configuration['TestingPCOpSys'] == 'Alma9':
    import uproot


##### Mapping functions

# To get the pad number from the chip, channel number and channel type
# map_dict: a dictionary containing the pad - channel mapping from corresponding file
# chip: chip number
# chan: channel number
# chantype: channel type (0 for normal, 1 for calib or 100 for CM)
def get_pad_id(map_dict, chip, chan, chantype): 
    if (chip, chan, chantype) in map_dict["PAD"]:
        return map_dict["PAD"][(chip, chan, chantype)]
    else:
        return 0


##### Plotting functions

# To plot the patches
# df: pandas DataFrame with the data
# mask: a mask to select specific data from the dataframe (eg. df['channeltype'] == 0)
# data_type: the type of data corresponding to the mask ('norm' for normal, 'calib' for calib, 
#                                             'cm0' for CM of type 0, 'cm1' for CM of type 1 or 'nc' for not connected)
# hb_type: the type of the board ("LF" for low density or "HF" for high density)
def create_patches(df, mask, data_type, hb_type = "LF"):
    patches = []
    local_mask = mask.copy()
    r = 0.43 * (1.18 / 0.82) #LD ~0.618cm
    if hb_type in ['HF', 'HB', 'HT', 'HL', 'HR']: 
        r = 0.28 * (0.74 / 0.55) # HD ~0.376cm
    for x, y in df.loc[local_mask, ["x", "y"]].values:
        angle = 0
        edgec = None
        if data_type == 'norm':
            ver = 6
            rad = r
        elif data_type == 'calib':
            ver = 6
            rad = 0.5 * r
            edgec = 'black'
        elif data_type == 'cm0':
            ver = 5
            rad = 0.75 * r
        elif data_type == 'cm1':
            ver = 4
            rad = 0.85 * r
            angle = np.radians(45)
        elif data_type == 'nc':
            ver = 100
            rad = 0.75 * r
        patch = RegularPolygon((x, y), numVertices = ver, radius = rad, orientation = angle, edgecolor = edgec, alpha = 0.9, lw=1.5)
        patches.append(patch)
    return patches

# Classes to create the legend
class HandlerHexagon(HandlerPatch):
    def create_artists(self, legend, orig_handle,
                       xdescent, ydescent, width, height, fontsize, trans):
        center = 0.5 * width - 0.5 * xdescent, 0.5 * height - 0.5 * ydescent
        p = RegularPolygon(xy=center, numVertices = 6, radius = 10, orientation=0, edgecolor = 'k')
        self.update_prop(p, orig_handle, legend)
        p.set_transform(trans)
        return [p]
class HandlerPentagon(HandlerPatch):
    def create_artists(self, legend, orig_handle,
                       xdescent, ydescent, width, height, fontsize, trans):
        center = 0.5 * width - 0.5 * xdescent, 0.5 * height - 0.5 * ydescent
        p = RegularPolygon(xy=center, numVertices = 5, radius = 10, orientation=0)
        self.update_prop(p, orig_handle, legend)
        p.set_transform(trans)
        return [p] 
class HandlerSquare(HandlerPatch):
    def create_artists(self, legend, orig_handle,
                       xdescent, ydescent, width, height, fontsize, trans):
        center = 0.5 * width - 0.5 * xdescent, 0.5 * height - 0.5 * ydescent
        p = RegularPolygon(xy=center, numVertices = 4, radius = 10, orientation=np.radians(45))
        self.update_prop(p, orig_handle, legend)
        p.set_transform(trans)
        return [p]
class HandlerCircle(HandlerPatch):
    def create_artists(self, legend, orig_handle,
                       xdescent, ydescent, width, height, fontsize, trans):
        center = 0.5 * width - 0.5 * xdescent, 0.5 * height - 0.5 * ydescent
        p = RegularPolygon(xy=center, numVertices = 100, radius = 10, orientation=0)
        self.update_prop(p, orig_handle, legend)
        p.set_transform(trans)
        return [p]

# To add the channel type legend to the plot
# axes: the plt.Axes object with the plot
# hb_type: the type of the board ("LF" for low density or "HF" for high density)
def add_channel_legend(axes, hb_type = "LF"):
    hexagon = RegularPolygon((0.5, 0.5), numVertices = 6, radius = 10, orientation = 0, edgecolor = 'k')
    pentagon = RegularPolygon((0.5, 0.5), numVertices = 5, radius = 10, orientation = 0)
    square = RegularPolygon((0.5, 0.5), numVertices = 4, radius = 10, orientation = np.radians(45))
    circle = RegularPolygon((0.5, 0.5), numVertices = 100, radius = 10, orientation = 0)
    if hb_type in ['LF', 'LR', 'LL', 'LB', 'LT', 'L5', 'HB', 'HL', 'HR', 'HT']:
        handles = [hexagon, pentagon, square, circle]
        labels = ['calib', 'CM0', 'CM1', 'NC']
    elif hb_type == "HF":
        handles = [hexagon, pentagon, square]
        labels = ['calib', 'CM0', 'CM1']
    
    patch_legend = axes.legend(handles, labels, loc = 'lower right', fontsize = 'small',
                               handler_map={hexagon: HandlerHexagon(), pentagon: HandlerPentagon(),
                                            square: HandlerSquare(), circle: HandlerCircle()})
    axes.add_artist(patch_legend)

def create_masks(df_data):
    
    # create the masks
    norm_mask = df_data["channeltype"] == 0
    norm_mask &= df_data['pad'] > 0

    calib_mask = df_data["channeltype"] == 1
    calib_mask &= df_data['pad'] > 0
    
    cm0_mask = df_data["channeltype"] == 100
    cm0_mask &= df_data["channel"] % 2 == 0

    cm1_mask = df_data["channeltype"] == 100
    cm1_mask &= df_data["channel"] % 2 == 1

    nc_mask = df_data["channeltype"] == 0
    nc_mask &= df_data['pad'] < 0

    return norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask
    
upplims = {'adc_mean': 400.,
           'adc_stdd': 8.,
           'adc_median': 400.,
           'adc_iqr': 8.,
           'inputdacs': 255.,
           'ileak': 40.}
zlabels = {'adc_mean': 'Pedestal [ADC Counts]',
           'adc_stdd': 'Noise [ADC Counts]',
           'adc_median': 'Median ADC Counts',
           'adc_iqr': 'IQR ADC Counts',
           'inputdacs': 'InputDAC',
           'ileak': r'Leakage Current [$\mu$A]'}


def _format_run_timestamp(label):
    m = re.search(r'run_(\d{8})_(\d{6})', label or '')
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S')
        tz = dt.astimezone().strftime('%Z')
        return dt.strftime(f'%B %-d, %Y  %H:%M:%S {tz}')
    except ValueError:
        return None


def _label_for_title(label):
    return re.sub(r'_?run_\d{8}_\d{6}', '', label or '').replace('_', ' ').strip()


# base function for hexmap plots
# plots hexagon patches, axes, etc.
# df: data frame
# column: name of column to plot
# hb_type: hexaboard density and geometry
# returns fig, ax, patch collection
def plot_hexmap_base(df, column, hb_type = "LF"):
    df_data = df # create clone to avoid conflict

    # modify colormap to highlight extrema - red for top bin, gray for bottom
    try:
        cmap = mpl.colormaps['viridis']
    except AttributeError:
        cmap = mpl.cm.get_cmap('viridis', 400)
    try:
        red = np.array([[1., 0., 0., 1.]])
        gray = np.array([[0.35, 0.35, 0.35, 1.]])
        cmap.set_under(gray)
        cmap.set_over(red)
    except ValueError:
        red = np.array([1., 0., 0., 1.])
        gray = np.array([0.35, 0.35, 0.35, 1.])
        cmap.set_under(gray)
        cmap.set_over(red)

    # create masks
    norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask = create_masks(df_data)    
    masks = [norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask]
    data_types = ['norm', 'calib', 'cm0', 'cm1', 'nc']

    # grab upper limit from dictionary
    # lower limit always zero
    upplim = upplims[column]

    fig, ax = plt.subplots(figsize = (16,12))

    patches = []
    colors = np.array([])

    # create patches
    for mask, data_type in zip(masks, data_types):
        local_mask = mask.copy()
        local_mask &= df_data[column] >= 0
        patches += create_patches(df_data, local_mask, data_type, hb_type = hb_type)
        colors = np.concatenate((colors, df_data[local_mask][column].values))
            
    patch_col = PatchCollection(patches, cmap = cmap, match_original = True)
    patch_col.set_array(colors)
        
    patch_col.set_clim([0.001, upplim])

    scale = 1.18 / 0.82 if hb_type[0] == 'L' else 0.74 / 0.55
    ax.set_xlim([-7.274 * scale, +7.274 * scale])
    ax.set_ylim([-7.09 * scale, +7.09 * scale])
    ax.set_xlabel('x pos [cm]')
    ax.set_ylabel('y pos [cm]')

    # print summary info to plot
    ax.text(5 * scale, 6.5 * scale, r'$\mu = '+str(round(np.mean(df_data[column][norm_mask | calib_mask]), 2))+'$')
    ax.text(5 * scale, 6 * scale, r'$\sigma = '+str(round(np.std(df_data[column][norm_mask | calib_mask]), 2))+'$')            

    zlab = zlabels[column]
    cb = plt.colorbar(patch_col, label = zlab, ax=ax)#, extend='both', extendrect=True)

    # add red triangle to indicate values above max are red
    trixy = np.array([[0, 1], [1, 1], [0.5, 1.04]])
    pt = mpl.patches.Polygon(trixy, transform=cb.ax.transAxes, 
                             clip_on=False, edgecolor='k', linewidth=0.7, 
                             facecolor=red, zorder=4, snap=True)
    cb.ax.add_patch(pt)
    # add gray rectangle to indcate zero values are gray
    recty = np.array([[0, 0], [1, 0], [1, -0.04], [0, -0.04]])
    pr = mpl.patches.Polygon(recty, transform=cb.ax.transAxes, 
                             clip_on=False, edgecolor='k', linewidth=0.7, 
                             facecolor=gray, zorder=4, snap=True)
    cb.ax.add_patch(pr)
    cb.ax.text(11./8., -0.18/8.*upplim, r'0', ha='center', va='center')
        
    # add the legend
    add_channel_legend(ax, hb_type = hb_type)
    return fig, ax, patch_col


# To plot the ADC graphs from a pandas dataFrame containing the data
# df: pandas DataFrame with the data
# figdir: the output directory for the plots
# hb_type: the type of the board ("LF" for low density or "HF" for high density)
# label: a label to put in the plot names
# live: boolean if live module
# BV: bias voltage
# plots adc_mean as Pedestal and adc_stdd as Noise
def plot_adc_hexmaps(df, figdir = "./", hb_type = "LF", label = None, live = False, BV = None, sen_thickness = None):

    print(" >> Hexmap: Plotting ADC hexmaps")
    df_data = df

    # create masks
    norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask = create_masks(df_data)
    masks = [norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask]
    data_types = ['norm', 'calib', 'cm0', 'cm1', 'nc']
    
    for column in ['adc_mean', 'adc_stdd']:
    
        # base plot
        fig, ax, patch_col = plot_hexmap_base(df_data, column, hb_type=hb_type)
    
        # for live module if actual channels have same noise as disconnected
        # channels, label. but only label if in low-BV pedestal run
        uncon = []
        if live and column == 'adc_stdd':
            # new 2025/7/30 - just use 1.2 ADC counts cut. real unbonded
            # detection requires more than one pedestal test, but still highlight
            # in plot for individual tests
            uncon = (df_data[column] < 1.2) & (df_data['adc_stdd'] > 0.)
        else:
            uncon = df_data[column] <= 0. # all false 

        # if actual channels have significantly higher value than normal
        # channels, label
        med_norm = df_data[column][norm_mask].median()
        mean_norm = df_data[column][norm_mask].mean()
        std_norm = df_data[column][norm_mask].std()
        if live and sen_thickness is not None:
            if column == 'adc_stdd':
                # compromise definition from https://indico.cern.ch/event/1602073/contributions/6752482/attachments/3159554/5613107/acroberts_noise_study_oct25.pdf
                # do not ground based on these labels! 
                if hb_type[0] == 'H' and sen_thickness == '1': noisy_limit = 3
                elif hb_type[0] == 'H' and sen_thickness == '2': noisy_limit = 2.5
                elif hb_type[0] == 'L' and sen_thickness == '2': noisy_limit = 5
                elif hb_type[0] == 'L' and sen_thickness == '3': noisy_limit = 4
                else: noisy_limit = 8
            else:
                noisy_limit = 200
        elif live:
            noisy_limit = (8 if column == 'adc_stdd' else 200)
        else:
            noisy_limit = (2 if column == 'adc_stdd' else 5000)

        highval = df_data[column] > noisy_limit
            
        # pick out channels with corrupted readout
        corrupted = df_data['corruption'] == 1
        
        # for all modules, label if zero or max value
        zeros = df_data[column] == 0
        maxes = df_data[column] >= upplims[column]

        # build channels to label
        labelchans = corrupted | zeros | maxes | highval | uncon

        # label
        for x, y, pad in df_data.loc[labelchans & (df_data['pad'] > 0), ["x", "y", "pad"]].values:
            ax.text(x, y-0.03, str(int(pad)), fontsize=14, ha='center', va='center', color='w')

        edgecolors = np.array([])
        edgewidths = np.array([])
        edgestyles = np.array([])

        # color edges of pads red if noisy, violet if corrupted, orange if unbonded
        edgeclr = np.array(['#ffffff00' for i in range(len(df_data))])
        edgeclr[calib_mask] = 'black'
        edgeclr[highval & (norm_mask | calib_mask)] = 'red'
        edgeclr[corrupted] = 'violet'
        if BV is not None:
            if live and BV <= 10.:
                edgeclr[uncon & (norm_mask | calib_mask)] = 'orange'

        edgesty = np.array(['-' for i in range(len(df_data))], dtype=(str, 20))
        edgesty[highval & (norm_mask | calib_mask)] = '--'
        edgesty[corrupted] = '-.'
        if BV is not None:
            if live and BV <= 10.:
                edgesty[uncon & (norm_mask | calib_mask)] = '-'
        
        edgewdth = np.array([1.5 for i in range(len(df_data))])
        edgewdth[highval & (norm_mask | calib_mask)] = 3    
        edgewdth[corrupted & (norm_mask | calib_mask)] = 3    
        if BV is not None:
            if live and BV <= 10.:
                edgewdth[uncon & (norm_mask | calib_mask)] = 3    

        for mask, data_type in zip(masks, data_types):
            # color/style edges of pads
            edgecolors = np.concatenate((edgecolors, edgeclr[mask]))
            edgewidths = np.concatenate((edgewidths, edgewdth[mask]))
            edgestyles = np.concatenate((edgestyles, edgesty[mask]))
              
        patch_col.set_linestyle(edgestyles)
        patch_col.set_edgecolor(edgecolors)
        patch_col.set_linewidth(edgewidths)

        ax.add_collection(patch_col)
        # print some info if it's a noise plot
        if column == 'adc_stdd':

            ndead = np.sum(zeros & ~corrupted & (df_data["pad"] > 0))
            nnoisy = np.sum(highval & ~corrupted & (df_data["pad"] > 0))
            ncorr = np.sum((corrupted) & (df_data["pad"] > 0))
            nuncon = np.sum(uncon & ~corrupted & (df_data["pad"] > 0))
            add_uncon = live and BV is not None and BV <= 10. and nuncon > 0
            tallylist = ['Channels:', 
                         f'{ndead} Dead',
                         f'{nnoisy} Noisy']
            if ncorr > 0:
                tallylist.insert(1, f'{ncorr} Corrupted')
            if add_uncon:
                tallylist.insert(-1, f'{nuncon} Unbonded')

            scale = 1.18 / 0.82 if hb_type[0] == 'L' else 0.74 / 0.55
            step = 0.5 * scale
            xlim = ax.get_xlim()[0] + 0.2
            initheight = ax.get_ylim()[0] + 0.2 + step * (len(tallylist) - 1)
            for i in range(len(tallylist)):
                ax.text(xlim, initheight - i * step, tallylist[i])
            ad_chip_geo(ax, hb_type = hb_type,
                        add_noisy = (nnoisy > 0),
                        add_uncon = add_uncon,
                        add_corrupted = (ncorr > 0))
        else:
            # add red dashed hex to label if high value even for adc_mean plot
            nhighval = np.sum(highval & ~corrupted & (df_data["pad"] > 0))
            ad_chip_geo(ax, hb_type = hb_type,
                        add_noisy = (nhighval > 0))
            
        # add run timestamp below bottom of colorbar, right-aligned
        ts = _format_run_timestamp(label)
        if ts:
            cb_ax = fig.axes[-1]
            cb_ax.text(1.0, -0.07, ts, transform=cb_ax.transAxes,
                       ha='right', va='top', fontsize=12)

        # add the title
        plt.title(_label_for_title(label))

        # save the figure
        figname = figdir + str(label) + "_" + column + ".png"
        plt.savefig(figname, bbox_inches='tight')
        plt.close()
    return 1

# Plots inputdac values as a hexmap from a pandas dataFrame containing the data
# This function adds the inputdac values to the df itself
# df: pandas DataFrame with the data
# inputdac_path: path to inputdac scan directory
# figdir: the output directory for the plots
# hb_type: the type of the board ("LF" for low density or "HF" for high density)
# label: a label to put in the plot names
# live: boolean if live module
# BV: bias voltage
def plot_inputdac_hexmaps(df, inputdac_path, figdir = "./", hb_type = "LF", label = None, live = False, BV = None):

    print(" >> Hexmap: Plotting inputdac hexmap")
    df_data = df

    # create masks
    norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask = create_masks(df_data)
    masks = [norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask]
    data_types = ['norm', 'calib', 'cm0', 'cm1', 'nc']
    
    column = 'inputdacs'

    # add inputdacs to df
    df_data = add_idacs_to_df(hb_type, df_data, inputdac_path)
    # base plot
    fig, ax, patch_col = plot_hexmap_base(df_data, column, hb_type=hb_type)

    labelchans = df_data[column] > 0.
    
    # label
    for x, y, pad in df_data.loc[labelchans & (df_data['pad'] > 0), ["x", "y", "pad"]].values:
        ax.text(x, y-0.03, str(int(pad)), fontsize=14, ha='center', va='center', color='w')

    ax.add_collection(patch_col)

    ts = _format_run_timestamp(label)
    if ts:
        cb_ax = fig.axes[-1]
        cb_ax.text(1.0, -0.07, ts, transform=cb_ax.transAxes,
                   ha='right', va='top', fontsize=12)

    # add the title
    plt.title(_label_for_title(label))

    # save the figure
    figname = figdir + str(label) + "_" + column + ".png"
    plt.savefig(figname, bbox_inches='tight')
    plt.close()
    return 1

# Plots leakage current per channel as a hexmap from a pandas dataFrame containing the data
# This function adds the inputdac and leakage current values to the df itself
# df: pandas DataFrame with the data
# inputdac_path: path to inputdac scan directory
# figdir: the output directory for the plots
# hb_type: the type of the board ("LF" for low density or "HF" for high density)
# label: a label to put in the plot names
# live: boolean if live module
# BV: bias voltage
def plot_ileak_hexmaps(df, inputdac_path, figdir = "./", hb_type = "LF", label = None, live = False, BV = None):

    print(" >> Hexmap: Plotting leakage current hexmap")
    df_data = df
    
    # create masks
    norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask = create_masks(df_data)
    masks = [norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask]
    data_types = ['norm', 'calib', 'cm0', 'cm1', 'nc']
    
    column = 'ileak'

    # add inputdacs and leakage current to df
    df_data = add_ileak_to_df(hb_type, df_data, inputdac_path)
    # base plot
    fig, ax, patch_col = plot_hexmap_base(df_data, column, hb_type=hb_type)

    labelchans = df_data[column] > 0.
    highval = df_data[column] > 30.

    # label all with ileak > 0.
    for x, y, pad in df.loc[labelchans & (df_data['pad'] > 0), ["x", "y", "pad"]].values:
        ax.text(x, y-0.03, str(int(pad)), fontsize=14, ha='center', va='center', color='w')

    edgecolors = np.array([])
    edgewidths = np.array([])
    edgestyles = np.array([])

    # color edges of pads red with dashed lines if ileak > 30muA
    edgeclr = np.array(['#ffffff00' for i in range(len(df_data))])
    edgeclr[highval & (norm_mask | calib_mask)] = 'red'

    edgesty = np.array(['-' for i in range(len(df_data))], dtype=(str, 20))
    edgesty[highval & (norm_mask | calib_mask)] = '--'
        
    edgewdth = np.array([1.5 for i in range(len(df_data))])
    edgewdth[highval & (norm_mask | calib_mask)] = 3    
    
    for mask, data_type in zip(masks, data_types):
        # color/style edges of pads
        edgecolors = np.concatenate((edgecolors, edgeclr[mask]))
        edgewidths = np.concatenate((edgewidths, edgewdth[mask]))
        edgestyles = np.concatenate((edgestyles, edgesty[mask]))
              
    patch_col.set_linestyle(edgestyles)
    patch_col.set_edgecolor(edgecolors)
    patch_col.set_linewidth(edgewidths)

    ax.add_collection(patch_col)

    nhighval = np.sum(highval & (df_data["pad"] > 0))
    tallylist = ['Channels:', 
                 f'{nhighval} High Current']
    
    scale = 1.18 / 0.82 if hb_type[0] == 'L' else 0.74 / 0.55
    step = 0.5 * scale
    xlim = ax.get_xlim()[0] + 0.2
    initheight = ax.get_ylim()[0] + 0.2 + step * (len(tallylist) - 1)
    for i in range(len(tallylist)):
        ax.text(xlim, initheight - i * step, tallylist[i])
                
    ad_chip_geo(ax, hb_type = hb_type,
                add_noisy = (nhighval > 0))

    ts = _format_run_timestamp(label)
    if ts:
        cb_ax = fig.axes[-1]
        cb_ax.text(1.0, -0.07, ts, transform=cb_ax.transAxes,
                   ha='right', va='top', fontsize=12)

    # add the title
    plt.title(_label_for_title(label))

    # save the figure
    figname = figdir + str(label) + "_" + column + ".png"
    plt.savefig(figname, bbox_inches='tight')
    plt.close()
    return 1

# collect inputdacs and add to dataframe
# df: dataframe
# inputdac_path: path to inputdac scan directory
# returns df
def add_idacs_to_df(hb_type, df, inputdac_path):

    df_data = df
    
    idacs = np.full_like(df_data['chip'], 0.)

    # load inputdacs
    dacout = {}
    with open(f'{inputdac_path}/inputdacs.yaml', 'r') as file:
        dacout = yaml.safe_load(file)

    # if pedestals never drop as idac increases, idac_scan outputs 0
    # but we want the maximum value instead. so load the last scan
    # and ensure we catch 0 idac but nonzero pedestal
    f = uproot.open(f'{inputdac_path}/inputdac_scan254.root')
    try:
        tree = f["runsummary"]["summary"]

        # different uproot functions for different OS =.=
        if configuration['TestingPCOpSys'] == 'Centos7':
            last_idac = tree.pandas.df()
        elif configuration['TestingPCOpSys'] == 'Alma9':
            last_idac = tree.arrays(library='pd')
            
    except:
        print(" -- Hexmap: No inputdac last run found")
        return 0

    # collect inputdac values by iterating over chips
    # XYZ will have to fix roc names?
    chips = roc_name_idx_mapping[hb_type]
    roc_idxs = [chips[i]['chip'] for i in range(len(chips))]
    roc_names = [chips[i]['config_json_key'] for i in range(len(chips))]

    # ensure roc names in yaml config keys - should always be the case
    # raises AssertionError which will be caught by func in ExternalPC
    for name in roc_names:
        assert name in dacout.keys()

    for idx, name in zip(roc_idxs, roc_names):
        thisroc = dacout[name]['sc']['ch']
        for key in thisroc.keys(): # normal channel numbers
            # grab inputdac
            if thisroc[key]['Inputdac'] != 0:
                idacs[(df_data['chip'] == idx) & (df_data['channel'] == key) & (df_data['channeltype'] == 0)] = thisroc[key]['Inputdac']
            # if inputdac is zero but pedestal still high, set inputdac to max
            else:
                this_idac = last_idac[(last_idac['chip'] == idx) & (last_idac['channel'] == key) & (last_idac['channeltype'] == 0)]
                if len(this_idac) == 1 and this_idac['adc_mean'].iloc[0] > 10.:
                    idacs[(df_data['chip'] == idx) & (df_data['channel'] == key) & (df_data['channeltype'] == 0)] = 255
                
        thisroc = dacout[name]['sc']['calib']
        for key in thisroc.keys(): # calib channel numbers
            # grab inputdac
            if thisroc[key]['Inputdac'] != 0:
                idacs[(df_data['chip'] == idx) & (df_data['channel'] == key) & (df_data['channeltype'] == 1)] = thisroc[key]['Inputdac']
            # if inputdac is zero but pedestal still high, set inputdac to max
            else:
                this_idac = last_idac[(last_idac['chip'] == idx) & (last_idac['channel'] == key) & (last_idac['channeltype'] == 1)]
                if len(this_idac) == 1 and this_idac['adc_mean'].iloc[0] > 10.:
                    idacs[(df_data['chip'] == idx) & (df_data['channel'] == key) & (df_data['channeltype'] == 1)] = 255

    # add to df
    df_data['inputdacs'] = idacs
    return df_data

# collect inputdacs, calculate leakage current, and add both to dataframe
# df: dataframe
# inputdac_path: path to inputdac scan directory
# returns df
def add_ileak_to_df(hb_type, df, inputdac_path):
    # convert inputdacs to leakage current in muA
    
    df_data = df
    # add inputdacs
    df_data = add_idacs_to_df(hb_type, df_data, inputdac_path)

    dacs = np.asarray(df_data['inputdacs'], dtype=np.uint8)
    bit2ileak = np.asarray([0.17,0.35,0.71,1.4,2.85,5,10,20])

    # create array of inputdac bits
    bits = ((dacs[:, None] >> np.arange(8)) & 1).astype(np.uint8)

    # bitwise multiply and sum
    df_data['ileak'] = np.sum(bits * bit2ileak, axis=1)
    return df_data
    
def plot_channels(df, figdir = "./", hb_type = "LF", label = None, live = False):
    print(" >> Hexmap: Plotting channels in 1D")
    df_data = df # create clone to avoid conflict                                                                                                                                                       

    norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask = create_masks(df)
    cm_mask = cm0_mask | cm1_mask

    masks = [norm_mask, calib_mask, cm_mask, nc_mask]
    data_types = ['Si Pads', 'Calibration', 'Common Mode', 'Not Connected']
    colors = ['k', 'b', 'r', 'gray']

    for column in df_data.columns:

        if column != 'adc_mean' and column != 'adc_stdd':
            continue

        ylab = 'Noise [ADC counts]' if column == 'adc_stdd' else 'Pedestal [ADC counts]'
        upplim = 400. if column == 'adc_mean' or column == 'adc_median' else 8.

        chips = set(df_data.chip)
        nchips = len(chips)

        fig = plt.figure(figsize=(16, 4*nchips))
        gs = fig.add_gridspec(nchips, 1)

        ax = [fig.add_subplot(gs[0,0])]
        for i in range(1, nchips):
            ax.append(fig.add_subplot(gs[i,0], sharex=ax[0]))

        fig.subplots_adjust(hspace=0.)

        ax[0].set_xlim([np.min(df_data.channel), np.max(df_data.channel)])

        for i in range(nchips):
            ax[i].set_ylabel(ylab, fontsize=20)
            ax[i].set_ylim([0., upplim])
            ax[i].text(3, upplim*0.8, f'Chip {i}')
            ax[i].set_xticks(np.linspace(0, 70, 15))
            ax[i].grid(True)
            
            # print summary info to plot                                                                                                                                                    
            ax[i].text(60, upplim*0.8, r'$\mu = '+str(round(np.mean(df_data[column][norm_mask | calib_mask][df_data.chip == i]), 2))+'$')
            ax[i].text(60, upplim*0.7, r'$\sigma = '+str(round(np.std(df_data[column][norm_mask | calib_mask][df_data.chip == i]), 2))+'$')

            for mask, type, color in zip(masks, data_types, colors):
                ax[i].scatter(df_data.channel[df_data.chip == i][mask], df_data[column][df_data.chip == i][mask], color=color, label=type)

                above_plot = df_data[(df_data.chip == i) & (df_data[column] > upplim) & mask]
                ax[i].scatter(above_plot.channel, np.full_like(above_plot.channel, upplim*0.95, dtype=float), color=color, marker=r'$\uparrow$', s=160)

            if i != 0:
                yticks = ax[i].yaxis.get_major_ticks()
                yticks[-1].set_visible(False)
            if i != nchips - 1:
                ax[i].tick_params(labelbottom=False)

        try:
            ax[0].legend(loc=(0.16, 1.01), fontsize=20, ncols=4, columnspacing=0.3, handletextpad=0.1)
        except TypeError:
            ax[0].legend(loc=(0.16, 1.01), fontsize=20, ncol=4, columnspacing=0.3, handletextpad=0.1)
            
        ax[-1].set_xlabel('Channel Number')

        # add the title
        ax[0].set_title(_label_for_title(label), y=1.25)

        ts = _format_run_timestamp(label)
        if ts:
            fig.subplots_adjust(bottom=0.05)
            fig.text(0.98, -0.01, ts, ha='right', va='bottom', fontsize=12)

        # save the figure
        figname = figdir + str(label) + "_" + column + "_channels.pdf"
        plt.savefig(figname, bbox_inches='tight')
        plt.close()
    return 1

def plot_pads(df, figdir = "./", hb_type = "LF", label = None, live = False):
    print(" >> Hexmap: Plotting pads in 1D")
    df_data = df # create clone to avoid conflict                                                                                                                                                       

    norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask = create_masks(df)
    cm_mask = cm0_mask | cm1_mask

    masks = [norm_mask, calib_mask, cm_mask, nc_mask]
    data_types = ['Si Pads', 'Calibration', 'Common Mode', 'Not Connected']
    colors = ['k', 'b', 'r', 'gray']

    for column in df_data.columns:

        if column != 'adc_mean' and column != 'adc_stdd':
            continue

        ylab = 'Noise [ADC counts]' if column == 'adc_stdd' else 'Pedestal [ADC counts]'
        upplim = 400. if column == 'adc_mean' or column == 'adc_median' else 8.

        fig, ax = plt.subplots(figsize=(16, 12))
        
        ax.set_xlabel('Pad Number')
        ax.set_ylabel(ylab)
        ax.set_xlim([np.min(df_data['pad']), np.max(df_data['pad'])])
        ax.set_ylim([0., upplim])

        ax.xaxis.set_major_locator(MultipleLocator(50))
        ax.xaxis.set_minor_locator(MultipleLocator(5))
        ax.grid(which='both')
            
        # print summary info to plot                                                                                                                                                    
        xloc = (np.max(df_data['pad']) - np.min(df_data['pad']))*0.02 + np.min(df_data['pad'])
        ax.text(xloc, upplim*0.95, r'$\mu = '+str(round(np.mean(df_data[column][norm_mask | calib_mask]), 2))+'$')
        ax.text(xloc, upplim*0.9, r'$\sigma = '+str(round(np.std(df_data[column][norm_mask | calib_mask]), 2))+'$')

        for mask, type, color in zip(masks, data_types, colors):
            ax.scatter(df_data['pad'][mask], df_data[column][mask], color=color, label=type, s=10)

            above_plot = df_data[(df_data[column] > upplim) & mask]
            ax.scatter(above_plot['pad'], np.full_like(above_plot.channel, upplim*0.99, dtype=float), color=color, marker=r'$\uparrow$', s=160)

        ax.legend(loc='upper right')

        # add the title
        ax.set_title(_label_for_title(label))

        ts = _format_run_timestamp(label)
        if ts:
            fig.subplots_adjust(bottom=0.05)
            fig.text(0.98, 0.02, ts, ha='right', va='bottom', fontsize=12)

        # save the figure
        figname = figdir + str(label) + "_" + column + "_pads.pdf"
        plt.savefig(figname, bbox_inches='tight')
        plt.close()
    return 1

                
##### Main functions: read ROOT file, decode to pandas and pass to plotting

# To make the hexmap plots from summary file
# fname: summary file name (relative path) that contains the data
# figdir: the output directory for the plots
# hb_type: the type of the board ("LF" for low density or "HF" for high density)
# label: a label to put in the plot names
def make_hexmap_plots_from_file(fname, figdir="./", hb_type=None, label=None, is_live=None, bv=None, idac_path=None):
    # fix label
    if label == None:
        label = os.path.basename(fname)
        label = label[:-5]

    segments = fname.split('/')
    for seg in segments:
        if re.match(r'^320[-MXP]', seg):
            moduleserial = seg.replace('-', '')

    if hb_type is None and label is not None:
        #moduleserial = fname.split('/')[-5]
        moduleserial = label.split('_')[0]
        density = moduleserial[4]
        shape = moduleserial[5]
        hb_type = density+shape

    if is_live is None:
        livemod = '320ML' in moduleserial or '320MH' in moduleserial
    else:
        livemod = is_live

    # sensor thickness needed for noisy categorization
    if is_live or livemod:
        senthk = moduleserial[6]
    else:
        senthk = None
        
    # fix figdir
    if figdir == None:
        figdir = os.path.dirname(fname)
    if not figdir.endswith("/"):
        figdir += "/"
    
    print(" >> Hexmap: Going to make plots for %s board from summary file %s into %s using label %s" %(hb_type, fname, figdir, label))

    # Open the hex data ".root" file and turn the contents into a pandas DataFrame.
    f = uproot.open(fname)
    try:
        tree = f["runsummary"]["summary"]

        # different uproot functions for different OS =.=
        if configuration['TestingPCOpSys'] == 'Centos7':
            df_data = tree.pandas.df()
        elif configuration['TestingPCOpSys'] == 'Alma9':
            df_data = tree.arrays(library='pd')

    except:
        print(" -- Hexmap: No tree found")
        return 0

    df_data = add_mapping(df_data, hb_type = hb_type)

    # find bias from label if not explict in args
    if bv is None and 'BV' in label:
        try:
            bv_from_label = label.split('BV')[1].split('_')[0]
            bv = int(bv_from_label)
        except Exception:
            print("     -- Hexmap: Can't find bias voltage, ignoring:", traceback.format_exc())
    
    # do plots
    #plot_hexmaps(df_data, figdir, hb_type, label, live=livemod, BV=bv)
    if not idac_path:
        plot_adc_hexmaps(df_data, figdir, hb_type, label, live=livemod, BV=bv, sen_thickness=senthk)
        plot_channels(df_data, figdir, hb_type, label, live=livemod)
        plot_pads(df_data, figdir, hb_type, label, live=livemod)
    elif idac_path:
        plot_adc_hexmaps(df_data, figdir, hb_type, label+'_after_IDACs', live=livemod, BV=bv, sen_thickness=senthk)
        plot_inputdac_hexmaps(df_data, idac_path, figdir, hb_type, label, live=livemod, BV=bv) 
        plot_ileak_hexmaps(df_data, idac_path, figdir, hb_type, label, live=livemod, BV=bv) 
    
    return 1

# Fetch a pedestal run from the database and return it as a pandas DataFrame.
# moduleserial: module or hexaboard serial (e.g. '320MLF2W2CM0103')
# modulestatus: module status string (e.g. 'Completely Encapsulated')
# BV: bias voltage (modules only; ignored for hexaboards)
# trimBV: for modules, bias voltage at which trimming was done (default 300);
#         for hexaboards, None for untrimmed or 0 for trimmed at 0V
# ind: index into the list of matching runs (default -1 = most recent)
# returns DataFrame, or None if no run found
def make_hexmap_plots_from_db(moduleserial, modulestatus, BV=None, trimBV=300, ind=-1):
    # lazy import to avoid circular dependency (DBTools imports from plot_summary)
    from DBTools import fetch_pedestal, hexaboard_fetch_pedestal

    is_module = moduleserial[3] == 'M'

    if is_module:
        runs = fetch_pedestal(moduleserial, BV, trimBV, modulestatus)
    elif moduleserial[3] == 'X':
        runs = hexaboard_fetch_pedestal(moduleserial, trimBV, modulestatus)
    else:
        print(f" -- Hexmap: Unrecognized serial format {moduleserial}")
        return None

    if not runs:
        print(f" -- Hexmap: No pedestal run found for {moduleserial} status={modulestatus}")
        return None

    run = runs[ind]

    dfkeys = ['chip', 'channel', 'channeltype',
              'adc_median', 'adc_iqr', 'tot_median', 'tot_iqr', 'toa_median', 'toa_iqr',
              'adc_mean', 'adc_stdd', 'tot_mean', 'tot_stdd', 'toa_mean', 'toa_stdd',
              'tot_efficiency', 'tot_efficiency_error', 'toa_efficiency', 'toa_efficiency_error',
              'x', 'y']
    df_dict = {key: run[key] for key in dfkeys}
    df_dict['pad'] = run['cell']
    df_dict['corruption'] = [0] * len(run['cell'])

    return pd.DataFrame(df_dict)


# Make hexmap plots from a pandas DataFrame.
# Intended for use with make_hexmap_plots_from_db() or pedestal_run_analysis.
# add_mapping() re-derives x/y/pad from geometry; safe to call even when df
# already has those columns (DB data), and correctly sets NC pad to negative.
def make_hexmap_plots_from_df(df_data, figdir="./", hb_type="LF", label=None, live=False, BV=None, sen_thickness=None):
    df_data = add_mapping(df_data, hb_type=hb_type)
    plot_adc_hexmaps(df_data, figdir, hb_type, label, live=live, BV=BV, sen_thickness=sen_thickness)
    plot_channels(df_data, figdir, hb_type, label, live=live)
    plot_pads(df_data, figdir, hb_type, label, live=live)
    return 1

if __name__ == "__main__":

    parser = ArgumentParser()
    # parser arguments
    parser.add_argument("infname", type=str, help="Input summary file name")
    parser.add_argument("-d", "--figdir", type=str, default=None, help="Plot directory, if None (default), use same directory as input file")
    parser.add_argument("-t", "--hb_type", type=str, default=None, help="Hexaboard type", choices=["LF","LL","LR","LB","LT","L5","HF","HR","HL","HT","HB"])
    parser.add_argument("-l", "--label", type=str, default=None, help="Label to use in plots")
    parser.add_argument("-b", "--bias_vol", type=int, default=None, help="bias voltage for the live module")
    parser.add_argument("--live", action=BooleanOptionalAction, help="Is live module")
    parser.add_argument("--hb", action=BooleanOptionalAction, help="Is hexaboard")
    parser.add_argument("--inputdacs", type=str, default=None, help="Path to inputdac scan folder")

    
    args = parser.parse_args()
    is_live = args.live
    assert args.live != args.hb
    make_hexmap_plots_from_file(args.infname, figdir=args.figdir, hb_type=args.hb_type, label=args.label, is_live=is_live, bv=args.bias_vol, idac_path=args.inputdacs)
