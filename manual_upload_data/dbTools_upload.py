"""
Stripped-down upload script for manually backfilling data collected before the
database was set up. Keeps only what's needed to push existing local data
(IV curves, pedestal test runs, pedestal plots, module_info) into Postgres.

Removed vs. the original: all PySimpleGUI/live-acquisition code, RH/T sensor
polling (add_RH_T), other_test_upload, summary_upload, bonding instructions,
trophy/mezzanine tracking, and all the readout_info/iv_info grading logic
(unconnected/dead/noisy-cell analysis) — none of that touches these four
tables, it's downstream analysis that reads *from* the DB after upload.

Fill in the __main__ block (or import these functions directly) to point at
wherever your manually-saved .pkl / .root / .png files actually live.
"""

import glob
import json
import os
import pickle
import traceback
import argparse
from datetime import datetime

import numpy as np
import yaml
import uproot  # Alma9 uproot API (arrays(library='pd'))
from PIL import Image

from PostgresTools import *  # upload_PostgreSQL, run_async
from hexmap.plot_summary import add_mapping, create_masks

with open('configuration.yaml', 'r') as file:
    configuration = yaml.safe_load(file)

# statusdict = {
#     'Untaped': 0, 'Taped': 1, 'Assembled': 2, 'Backside Bonded': 3,
#     'Backside Encapsulated': 4, 'Completely Bonded': 5, 'Bonds Reworked': 6,
#     'Completely Encapsulated': 7, 'Bolted': 8,
#     'Frontside Bonded': 5, 'Frontside Encapsulated': 7,
# }

statusdict = {
    'Completely Encapsulated': 7
}

def run_to_datetime(runname):
    """Parses a run directory name (…_YYYYMMDD_HHMMSS…) into a datetime."""
    runyr = int(runname.split('_')[1][0:4])
    runmon = int(runname.split('_')[1][4:6])
    runday = int(runname.split('_')[1][6:8])
    runhr = int(runname.split('_')[2][0:2])
    runmin = int(runname.split('_')[2][2:4])
    runsec = int(runname.split('_')[2][4:6])
    return datetime(year=runyr, month=runmon, day=runday,
                     hour=runhr, minute=runmin, second=runsec)


# ---------------------------------------------------------------------------
# module_info — just the name, nothing else
# ---------------------------------------------------------------------------
def module_info_upload(moduleserial):
    db_upload = {'module_name': moduleserial}
    result = run_async(upload_PostgreSQL(table_name='module_info', db_upload_data=db_upload))
    print(f"   >> DBTools: Uploaded module_info (name only) for {moduleserial}")
    return result


# ---------------------------------------------------------------------------
# module_iv_test
# ---------------------------------------------------------------------------
def iv_upload(moduleserial, datadict, modulestatus, inspector, comment=None):
    """
    datadict must contain the same keys the original GUI IV routine produced:
      'data'  -> Nx4 array: [program_v, meas_v, meas_i, meas_r]
      'RH', 'Temp', 'datetime'
    """
    data = datadict['data']
    v1, v2 = 500, 850
    try:
        ratio = float(data[:, 2][np.argwhere(data[:, 0] == v2)] /
                       data[:, 2][np.argwhere(data[:, 0] == v1)])
    except Exception:
        ratio = 0.

    db_upload_iv = {
        'module_name': moduleserial,
        'rel_hum': str(datadict['RH']),
        'temp_c': str(datadict['Temp']),
        'status': statusdict[modulestatus],
        'status_desc': modulestatus,
        'grade': '',
        'ratio_i_at_vs': ratio,
        'ratio_at_vs': [float(v1), float(v2)],
        'program_v': data[:, 0].tolist(),
        'meas_v': data[:, 1].tolist(),
        'meas_i': data[:, 2].tolist(),
        'meas_r': data[:, 3].tolist(),
        'date_test': datadict['datetime'].date(),
        'time_test': datadict['datetime'].time(),
        'inspector': inspector,
        'comment': comment,
    }

    result = run_async(upload_PostgreSQL(table_name='module_iv_test', db_upload_data=db_upload_iv))
    print(f"   >> DBTools: Uploaded IV curve of {moduleserial}")
    return result


def iv_upload_from_pkl(pklpath, moduleserial, modulestatus, inspector, comment=None):
    """Loads a previously-saved IV .pkl (as written by the old iv_save()) and uploads it."""
    with open(pklpath, 'rb') as f:
        datadict = pickle.load(f)
    return iv_upload(moduleserial, datadict, modulestatus, inspector, comment=comment)


# ---------------------------------------------------------------------------
# module_pedestal_test  (reads pedestal_run0.root, uploads the summary row)
# ---------------------------------------------------------------------------
def pedestal_upload(rundir, moduleserial, modulestatus, inspector,
                     RH=None, T=None, comment=None, trimval=None):
    """
    rundir: path to one pedestal run directory containing
            pedestal_run0.root and initial_full_config.yaml
    """
    fname = os.path.join(rundir, 'pedestal_run0.root')
    f = uproot.open(fname)
    try:
        summary = f["runsummary"]["summary"]
        df_data = summary.arrays(library='pd')
    except Exception:
        print('   -- DBTools exception:', traceback.format_exc())
        return None

    density = moduleserial[4]
    shape = moduleserial[5]
    sen_thickness = moduleserial[6]
    hb_type = density + shape

    df_data = add_mapping(df_data, hb_type=hb_type)
    norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask = create_masks(df_data)

    zeros = df_data['adc_stdd'] == 0
    if '320M' in moduleserial and sen_thickness is not None:
        if density == 'H' and sen_thickness == '1':
            noisy_limit = 3
        elif density == 'H' and sen_thickness == '2':
            noisy_limit = 2.5
        elif density == 'L' and sen_thickness == '2':
            noisy_limit = 5
        elif density == 'L' and sen_thickness == '3':
            noisy_limit = 4
        else:
            noisy_limit = 8
    elif '320M' in moduleserial:
        noisy_limit = 8
    else:
        noisy_limit = 2
    highval = df_data['adc_stdd'] > noisy_limit

    count_bad_cells = np.sum(zeros & (df_data["pad"] > 0)) + \
        np.sum(highval & (df_data["pad"] > 0) & ~calib_mask)
    list_dead_cells = df_data["pad"][zeros & (df_data["pad"] > 0)].tolist()
    list_noisy_cells = df_data["pad"][highval & (df_data["pad"] > 0) & ~calib_mask].tolist()

    rundirname = rundir.rstrip('/').split('/')[-1]
    runtime = run_to_datetime(rundirname)

    test_config_yaml_path = os.path.join(rundir, 'initial_full_config.yaml')
    with open(test_config_yaml_path, 'r') as file:
        test_config = yaml.safe_load(file)
    test_config_json_string = json.dumps(test_config)

    namekey = 'module_name' if '320M' in moduleserial else 'hxb_name'
    db_upload_ped = {
        namekey: moduleserial,
        'status': statusdict[modulestatus],
        'status_desc': modulestatus,
        'rel_hum': str(RH) if RH is not None else None,
        'temp_c': str(T) if T is not None else None,
        'count_bad_cells': count_bad_cells,
        'list_dead_cells': list_dead_cells,
        'list_noisy_cells': list_noisy_cells,
        'date_test': runtime.date(),
        'time_test': runtime.time(),
        'inspector': inspector,
        'comment': comment,
        'trim_bias_voltage': trimval,
        'cell': df_data['pad'].tolist(),
        'pedestal_config_json': test_config_json_string,
    }

    dfkeys = ['chip', 'channel', 'channeltype', 'adc_median', 'adc_iqr', 'tot_median', 'tot_iqr',
              'toa_median', 'toa_iqr', 'adc_mean', 'adc_stdd', 'tot_mean', 'tot_stdd', 'toa_mean',
              'toa_stdd', 'tot_efficiency', 'tot_efficiency_error', 'toa_efficiency',
              'toa_efficiency_error', 'x', 'y', 'corruption']
    for key in dfkeys:
        db_upload_ped[key] = df_data[key].tolist()
    db_upload_ped['corruption'] = [bool(v) for v in db_upload_ped['corruption']]

    if 'BV' in rundir and '320M' in moduleserial:
        for seg in rundir.split('_'):
            if 'BV' in seg:
                db_upload_ped['bias_vol'] = int(seg.split('BV')[1].rstrip('\n '))
        db_upload_ped['list_disconnected_cells'] = []
    elif '320M' in moduleserial:
        db_upload_ped['bias_vol'] = -1
        db_upload_ped['list_disconnected_cells'] = []

    table = 'module_pedestal_test' if '320M' in moduleserial else 'hxb_pedestal_test'
    result = run_async(upload_PostgreSQL(table_name=table, db_upload_data=db_upload_ped))
    print(f"   >> DBTools: Uploaded pedestal run of {moduleserial} from {rundir}")
    return result


def batch_pedestal_upload(basepath, moduleserial, modulestatus, inspector):
    """Uploads every run under basepath/pedestal_run/* for one module."""
    runs = sorted(glob.glob(f'{basepath}/pedestal_run/*'))
    for rundir in runs:
        if(rundir.endswith('trimmed300') and 'BV300' in rundir):
            print(f"   >> DBTools: Uploading pedestal run from {rundir} for {moduleserial}")
            pedestal_upload(rundir, moduleserial, modulestatus, inspector)


# ---------------------------------------------------------------------------
# module_pedestal_plots
# ---------------------------------------------------------------------------
def compress_png(image_path):
    img = Image.open(image_path)
    img = img.convert("P", palette=Image.ADAPTIVE, colors=256)
    img.save(image_path, optimize=True)

def find_hexpath_prefix(outdir, moduleserial):
    matches = sorted(glob.glob(f'{outdir}/{moduleserial}_run*_adc_mean.png'))
    matches.sort()
    hexPrefix = []
    for m in matches:
        if 'BV300' in m and 'trimmed300' in m:
            hexPrefix.append(m)
    print(hexPrefix)
    return hexPrefix[-1][:-len('_adc_mean.png')]

def plots_upload(rundir, moduleserial, modulestatus, inspector,
                  trimval=None, comment=None):

    hexpath_prefix = find_hexpath_prefix(rundir, moduleserial)
    print(hexpath_prefix)
    hexpaths = glob.glob(f'{hexpath_prefix}_*.png')
    hexmean = hexstdd = None
    for path in hexpaths:
        compress_png(path)
        if 'mean' in path:
            with open(path, 'rb') as f:
                hexmean = f.read()
        elif 'stdd' in path:
            with open(path, 'rb') as f:
                hexstdd = f.read()

    noise = [open(p, 'rb').read() for p in glob.glob(rundir + '/noise_vs_channel_chip*.png')]
    pedestal = [open(p, 'rb').read() for p in glob.glob(rundir + '/pedestal_vs_channel_chip*.png')]
    totnoise = [open(p, 'rb').read() for p in glob.glob(rundir + '/total_noise_chip*.png')]

    db_upload_plots = {
        'module_name': moduleserial,
        'status': statusdict[modulestatus],
        'status_desc': modulestatus,
        'adc_mean_hexmap': hexmean,
        'adc_std_hexmap': hexstdd,
        'noise_channel_chip': noise,
        'pedestal_channel_chip': pedestal,
        'total_noise_chip': totnoise,
        'trim_bias_voltage': trimval,
        'inspector': inspector,
        'comment_plot_test': comment,
    }

    result = run_async(upload_PostgreSQL(table_name='module_pedestal_plots', db_upload_data=db_upload_plots))
    print(f"   >> DBTools: Uploaded pedestal plots of {moduleserial}")
    return result


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Manually backfill module_iv_test, module_pedestal_test, "
                     "module_pedestal_plots, and module_info from previously "
                     "saved local data.")
    parser.add_argument('-m', '--module', required=True, help="Module serial number")
    parser.add_argument('-s', '--status', required=False, help="Module status (e.g. 'Completely Encapsulated')")
    parser.add_argument('-i', '--inspector', required=True, help="Inspector name")
    args = parser.parse_args()

    args.status = args.status if args.status is not None else 'Completely Encapsulated'
    #args.module = args.module.replace('-', '')
    #print("Module", args.module)
    #module_info_upload(args.module)

    # Fill these in / loop over your saved data as needed, e.g.:
    #batch_pedestal_upload('/home/rchudasa/data/320-ML-F3TC-TT-0245/Completely_Encapsulated_2026-02-20', args.module, args.status, args.inspector)
    #iv_upload_from_pkl('/home/rchudasa/data/320-ML-F3TC-TT-0245/Completely_Encapsulated_2026-02-20/320-ML-F3TC-TT-0245_IVset_2026-02-20_142134_None.pkl', args.module, args.status, args.inspector)
    plots_upload('/home/rchudasa/data/320-ML-F3TC-TT-0245/Completely_Encapsulated_2026-02-20',  args.module, args.status, args.inspector)