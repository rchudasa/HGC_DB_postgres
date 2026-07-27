import PySimpleGUI as sg
import numpy as np
import traceback
import matplotlib.pyplot as plt
import pickle
from argparse import ArgumentParser
from datetime import datetime 
import os
from PostgresTools import *
import pandas as pd
import glob
import asyncio
import asyncpg
from datetime import datetime, date
from hexmap.plot_summary import *
from functools import reduce
import json

import yaml
configuration = {}
with open('configuration.yaml', 'r') as file:
    configuration = yaml.safe_load(file)

# different versions of uproot for each OS =.=
if configuration['TestingPCOpSys'] == 'Centos7':
    import uproot3 as uproot
elif configuration['TestingPCOpSys'] == 'Alma9':
    import uproot
    
#statusdict = {'Untaped': 0, 'Taped': 1, 'Assembled': 2, 'Backside Bonded': 3, 'Backside Encapsulated': 4, 'Frontside Bonded': 5, 'Bonds Reworked': 6, 'Frontside Encapsulated': 7, 'Bolted': 8}
statusdict = {'Untaped': 0, 'Taped': 1, 'Assembled': 2, 'Backside Bonded': 3, 'Backside Encapsulated': 4, 'Completely Bonded': 5, 'Bonds Reworked': 6, 'Completely Encapsulated': 7, 'Bolted': 8, 'Frontside Bonded': 5, 'Frontside Encapsulated': 7}
    
def iv_save(datadict, state):
    """
    Takes the IV curve output dict and saves it to a pkl file. Returns the path to the pkl file.
    """

    moduleserial = state['-Module-Serial-']
    outdir = state['-Output-Subdir-']
    with open(f'{configuration["DataLoc"]}/{outdir}/{moduleserial}_IVset_{datadict["date"]}_{datadict["time"].replace(":", "")}_{datadict["RH"]}.pkl', 'wb') as datafile:
        pickle.dump(datadict, datafile)

    return f'{configuration["DataLoc"]}/{outdir}/{moduleserial}_IVset_{datadict["date"]}_{datadict["time"].replace(":", "")}_{datadict["RH"]}_{datadict["Temp"]}.pkl'
        
def read_table(tablename, printall=False):
    """
    Reads the table in the local database of the given name. If printall is true, prints all rows in the db table. If printall
    is false, prints only the most recently uploaded row.
    """
    
    result = run_async(fetch_PostgreSQL(tablename))
    
    if not printall:
        print(f'   >> DBTools: Last upload to {tablename}: {result[0]}')
    else:
        print(f'   >> DBTools: Printing all rows in {tablename}:')
        for r in result:
            print(r)
   
def fetch_pedestal(moduleserial, BV, trimBV, modulestatus):
    """
    Reads module_pedestal_test in the local database and returns the most recent test with the requested
    module serial number, bias voltage, and trimming conditions
    """

    result = run_async(get_pedestal(moduleserial, BV, trimBV, modulestatus))

    runs = []
    
    for r in result:
        runs.append(r)

    if runs == []:

        result = run_async(get_pedestal(moduleserial, BV, None, modulestatus))
        
        for r in result:
            runs.append(r)
        
    return runs     
        
def fetch_ileak_estimate(moduleserial, BV, modulestatus):
    """
    Reads module_ileak_estimate in the local database and returns the most recent test with the requested
    module serial number, bias voltage, and status
    """

    result = run_async(get_ileak_estimate(moduleserial, BV, modulestatus))
    
    runs = []    
    for r in result:
        runs.append(r)

    return runs     
        
def hexaboard_fetch_pedestal(hxbserial, trimmed, status):
    """
    Reads hxb_pedestal_test in the local database and returns the most recent test with the requested
    module serial number, bias voltage, and trimming conditions
    """

    result = run_async(fetch_serial_PostgreSQL('hxb_pedestal_test', hxbserial))
    
    
    runs = []
    
    for r in result:
        if trimmed is None and r['trim_bias_voltage'] is None and r['status_desc'] == status:
            runs.append(r)
        elif r['trim_bias_voltage'] == trimmed and r['status_desc'] == status:
            runs.append(r)

    return runs        
        
def fetch_iv(moduleserial, modulestatus, dry=True, roomtemp=True):
    """
    Reads module_iv_test or hxb_pedestal_test in the local database and returns the most recent test with the requested
    module serial number, bias voltage, and trimming conditions
    """

    result = run_async(fetch_serial_PostgreSQL('module_iv_test', moduleserial))

    runs = []
    
    for r in result:
        try:
            RH = float(r['rel_hum'])
            T = float(r['temp_c'])
        except ValueError: # RH / T cannot be converted to a float
            continue
        if roomtemp:
            req1 = (RH <= 12) if dry else (RH >= 20)
            req2 = (T >= 10 and T <= 30)
        else: # cold IV
            req1 = True # RH when cold not super useful b/c so little moisture in air
            req2 = (T <= -20)
        if req1 and req2 and r['status_desc'] == modulestatus:
            runs.append(r)

    return runs        

def fetch_iv_all(moduleserial):
    """
    Reads module_iv_test or hxb_pedestal_test in the local database and returns the most recent test with the requested
    module serial number, bias voltage, and trimming conditions
    """

    result = run_async(fetch_serial_PostgreSQL('module_iv_test', moduleserial))

    return result

# convert run name to date and time
def run_to_datetime(runname):
    runyr = int(runname.split('_')[1][0:4])
    runmon = int(runname.split('_')[1][4:6])
    runday = int(runname.split('_')[1][6:8])

    runhr = int(runname.split('_')[2][0:2])
    runmin = int(runname.split('_')[2][2:4])
    runsec = int(runname.split('_')[2][4:6])

    dt = datetime(year = runyr, month = runmon, day = runday,
                  hour = runhr, minute = runmin, second = runsec)
    return dt


def pedestal_upload(state, ind=-1):
    """
    Uploads the resultant data of a pedestal_run to the local database. The module serial and other information is read from the state dict. Unless
    otherwise specified, uploads the most recent run. Includes the RH and T from the pedestal run which are read from the state dict. 
    """
    
    moduleserial = state['-Module-Serial-']

    outdir = state['-Output-Subdir-']
    runs = glob.glob(f'{configuration["DataLoc"]}/{outdir}/pedestal_run/*')
    runs.sort()
    fname = runs[ind]+'/pedestal_run0.root'

    print(f"   >> DBTools: Uploading pedestal run of {moduleserial} board from summary file {fname} into database")

    # Open the hex data ".root" file and turn the contents into a pandas DataFrame.
    f = uproot.open(fname)
    try:
        summary = f["runsummary"]["summary"]
        unpacker = f["unpacker_data"]["hgcroc"]
        
        # different uproot functions for different OS =.=
        if configuration['TestingPCOpSys'] == 'Centos7':
            df_data = summary.pandas.df()
            df_unp = unpacker.pandas.df()
        elif configuration['TestingPCOpSys'] == 'Alma9':
            df_data = summary.arrays(library='pd')
            df_unp = unpacker.arrays(library='pd')

    except Exception:
        print('   -- DBTools exception:', traceback.format_exc())
        return 0

    density = moduleserial[4]
    shape = moduleserial[5]
    sen_thickness = moduleserial[6]
    hb_type = density+shape

    df_data = add_mapping(df_data, hb_type = hb_type)

    norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask = create_masks(df_data)

    # count dead/noisy channels
    zeros = df_data['adc_stdd'] == 0

    if ('320M' in moduleserial) and (sen_thickness is not None):
        # compromise definition from https://indico.cern.ch/event/1602073/contributions/6752482/attachments/3159554/5613107/acroberts_noise_study_oct25.pdf
        # do not ground based on these labels! definition WIP
        if density == 'H' and sen_thickness == '1': noisy_limit = 3
        elif density == 'H' and sen_thickness == '2': noisy_limit = 2.5
        elif density == 'L' and sen_thickness == '2': noisy_limit = 5
        elif density == 'L' and sen_thickness == '3': noisy_limit = 4
        else: noisy_limit = 8
    elif '320M' in moduleserial:
        noisy_limit = 8
    else:
        noisy_limit = 2
    highval = df_data['adc_stdd'] > noisy_limit
    
    count_bad_cells = np.sum((zeros) & (df_data["pad"] > 0)) + np.sum(highval & (df_data["pad"] > 0) & ~(calib_mask))
    list_dead_cells = df_data["pad"][zeros & (df_data["pad"] > 0)].tolist()
    list_noisy_cells = df_data["pad"][highval & (df_data["pad"] > 0) & ~(calib_mask)].tolist()

    print('   >> DBTools: count bad cells', count_bad_cells, 'list dead', list_dead_cells, 'list noisy', list_noisy_cells)

    just_one_channel = df_unp[(df_unp.chip == 0) & (df_unp.channel == 0) & (df_unp.half == 0)]
    adc_frac_unc = 1. / np.sqrt(float(len(just_one_channel)))
    
    if '-Box-RH-' not in state.keys(): # should already exist
        add_RH_T(state)
    RH = str(state['-Box-RH-'])
    T = str(state['-Box-T-'])
    
    now = datetime.now()

    comment = None
    if len(state['-Output-Subdir-'].split('/')) == 3:
        comment = state['-Output-Subdir-'].split('/')[2]
    
    trimval = None if '-Pedestals-Trimmed-' not in state.keys() else (0. if state['-Pedestals-Trimmed-'] == True else float(state['-Pedestals-Trimmed-']))

    # grab test configuration .yaml file and convert to json to upload
    test_config_yaml_path = runs[ind]+'/initial_full_config.yaml'
    test_config = {}
    with open(test_config_yaml_path, 'r') as file:
        test_config = yaml.safe_load(file)
    test_config_json_string = json.dumps(test_config)

    # get datetime from path
    rundir = runs[ind].split('/')[-1]
    runtime = run_to_datetime(rundir)
    
    # build upload row list
    namekey = 'module_name' if '320M' in moduleserial else 'hxb_name'
    db_upload_ped = {namekey: moduleserial,
                     'status': statusdict[state['-Module-Status-']],
                     'status_desc': state['-Module-Status-'],
                     'rel_hum': RH,
                     'temp_c': T,
                     'count_bad_cells': count_bad_cells,
                     'list_dead_cells': list_dead_cells,
                     'list_noisy_cells':list_noisy_cells,
                     'date_test': runtime.date(),
                     'time_test': runtime.time(),
                     'inspector': state['-Inspector-'],
                     'comment': comment,
                     'trim_bias_voltage': trimval,
                     'cell': df_data['pad'].tolist(), # rename pad -> cell
                     'pedestal_config_json': test_config_json_string,
                     }

    dfkeys = ['chip', 'channel', 'channeltype', 'adc_median', 'adc_iqr', 'tot_median', 'tot_iqr', 'toa_median', 'toa_iqr',
              'adc_mean', 'adc_stdd', 'tot_mean', 'tot_stdd', 'toa_mean', 'toa_stdd', 'tot_efficiency', 'tot_efficiency_error',
              'toa_efficiency', 'toa_efficiency_error', 'x', 'y', 'corruption']
    for key in dfkeys:
        db_upload_ped[key] = df_data[key].tolist()
    db_upload_ped['corruption'] = [bool(v) for v in db_upload_ped['corruption']]

    # if live module, add the bias voltage to the row list
    if 'BV' in runs[ind] and '320M' in moduleserial:
        segments = runs[ind].split('_')
        for seg in segments:
            if 'BV' in seg:
                BV = int(seg.split('BV')[1].rstrip('\n '))
        db_upload_ped['bias_vol'] = BV
        db_upload_ped['list_disconnected_cells'] = [] ### XYZ fix
        if '-Leakage-Current-' in state.keys(): # add measured leakage current
            db_upload_ped['meas_leakage_current'] = state['-Leakage-Current-']
    elif '320M' in moduleserial:
        BV = -1
        db_upload_ped['bias_vol'] = BV
        db_upload_ped['list_disconnected_cells'] = [] ### XYZ fix
    else:
        pass
    
    if '-Trophy-Serial-' in state.keys():
        db_upload_ped['trophy_board_name'] = state['-Trophy-Serial-']
        
    table = 'module_pedestal_test' if ('320M' in moduleserial) else 'hxb_pedestal_test'

    # upload
    try:
        db_upload_ped['inverse_sqrt_n'] = adc_frac_unc
        result = run_async(upload_PostgreSQL(table_name = table, db_upload_data = db_upload_ped))
    except:
        db_upload_ped.pop('inverse_sqrt_n', None)
        result = run_async(upload_PostgreSQL(table_name = table, db_upload_data = db_upload_ped))

    print(f"   >> DBTools: Uploaded pedestal run of {moduleserial}!")
    
    read_table(table)

def ileak_estimate_upload(state, ind=-1):
    """
    Uploads the resultant data of a leakage current estimation run to the local database. The module serial and other information is
    read from the state dict. Unless otherwise specified, uploads the most recent run, including pedestals and noise of the adjacent
    pedestal runs. Includes the RH and T from the run which are read from the state dict. 
    """
    
    moduleserial = state['-Module-Serial-']

    outdir = state['-Output-Subdir-']
    runs = glob.glob(f'{configuration["DataLoc"]}/{outdir}/pedestal_run/*')
    runs.sort()
    ped_fname_before = runs[ind-1]+'/pedestal_run0.root'
    ped_fname_after = runs[ind]+'/pedestal_run0.root'

    idac_runs = glob.glob(f'{configuration["DataLoc"]}/{outdir}/inputdac_scan/*')
    idac_runs.sort()
    idac_path = idac_runs[ind]
    
    print(f"   >> DBTools: Uploading leakage current estimate of {moduleserial} board from inputdac scan {idac_path} and pedestal summary files {ped_fname_before} and {ped_fname_after} into database")

    # Open the hex data ".root" file and turn the contents into a pandas DataFrame.
    f_before = uproot.open(ped_fname_before)
    f_after = uproot.open(ped_fname_after)
    try:
        summary_before = f_before["runsummary"]["summary"]
        unpacker = f_before["unpacker_data"]["hgcroc"] # assume number of samples does not change
        summary_after = f_after["runsummary"]["summary"]
        
        # different uproot functions for different OS =.=
        if configuration['TestingPCOpSys'] == 'Centos7':
            df_data_before = summary_before.pandas.df()
            df_unp = unpacker.pandas.df()
            df_data_after = summary_after.pandas.df()
        elif configuration['TestingPCOpSys'] == 'Alma9':
            df_data_before = summary_before.arrays(library='pd')
            df_unp = unpacker.arrays(library='pd')
            df_data_after = summary_after.arrays(library='pd')

    except Exception:
        print('   -- DBTools exception:', traceback.format_exc())
        return 0

    density = moduleserial[4]
    shape = moduleserial[5]
    hb_type = density+shape

    df_data_before = add_mapping(df_data_before, hb_type = hb_type)
    df_data_after = add_mapping(df_data_after, hb_type = hb_type)

    df_data_after = add_ileak_to_df(hb_type, df_data_after, idac_path)
    
    norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask = create_masks(df_data_before) # masks the same between before and after

    # fractional uncertainty
    just_one_channel = df_unp[(df_unp.chip == 0) & (df_unp.channel == 0) & (df_unp.half == 0)]
    adc_frac_unc = 1. / np.sqrt(float(len(just_one_channel)))
    
    if '-Box-RH-' not in state.keys(): # should already exist
        add_RH_T(state)
    RH = str(state['-Box-RH-'])
    T = str(state['-Box-T-'])
    
    now = datetime.now()

    comment = None
    if len(state['-Output-Subdir-'].split('/')) == 3:
        comment = state['-Output-Subdir-'].split('/')[2]
    
    trimval = None if '-Pedestals-Trimmed-' not in state.keys() else (0. if state['-Pedestals-Trimmed-'] == True else float(state['-Pedestals-Trimmed-']))

    # grab test configuration .yaml file and convert to json to upload
    # use .yaml config from before idac scan
    test_config_yaml_path = runs[ind-1]+'/initial_full_config.yaml' # before scan 

    test_config = {}
    with open(test_config_yaml_path, 'r') as file:
        test_config = yaml.safe_load(file)
    test_config_json_string = json.dumps(test_config)

    # grab inputdac_scan output .yaml file and convert to json to upload
    idac_output_yaml_path = idac_path+'/inputdacs.yaml'
    idac_out = {}
    with open(idac_output_yaml_path, 'r') as file:
        idac_out = yaml.safe_load(file)
    idac_output_json_string = json.dumps(idac_out)

    # get datetime from path
    rundir = runs[ind].split('/')[-1]
    runtime = run_to_datetime(rundir)
    
    # build upload row list
    db_upload_ileak = {'module_name': moduleserial,
                       'status': statusdict[state['-Module-Status-']],
                       'status_desc': state['-Module-Status-'],
                       'rel_hum': RH,
                       'temp_c': T,
                       'date_test': runtime.date(),
                       'time_test': runtime.time(),
                       'inspector': state['-Inspector-'],
                       'comment': comment,
                       'trim_bias_voltage': trimval,
                       'chip': df_data_before['chip'].tolist(),
                       'channel': df_data_before['channel'].tolist(),
                       'channeltype': df_data_before['channeltype'].tolist(),
                       'cell': df_data_before['pad'].tolist(), # rename pad -> cell
                       'input_config_json': test_config_json_string,
                       'pedestal_pre_inputdac': df_data_before['adc_mean'].tolist(),
                       'noise_pre_inputdac': df_data_before['adc_stdd'].tolist(),
                       'pedestal_post_inputdac': df_data_after['adc_mean'].tolist(),
                       'noise_post_inputdac': df_data_after['adc_stdd'].tolist(),
                       'cell_leakage_current_mua': df_data_after['ileak'].tolist(),
                       'output_inputdac': df_data_after['inputdacs'].tolist(),
                       'output_inputdac_json': idac_output_json_string,
                       }

    # if live module, add the bias voltage to the row list
    if 'BV' in runs[ind] and '320M' in moduleserial:
        segments = runs[ind].split('_')
        for seg in segments:
            if 'BV' in seg:
                BV = int(seg.split('BV')[1].rstrip('\n '))
        db_upload_ileak['bias_vol'] = BV
        if '-Leakage-Current-' in state.keys(): # add measured leakage current
            db_upload_ileak['meas_leakage_current'] = state['-Leakage-Current-']
    elif '320M' in moduleserial:
        BV = -1
        db_upload_ileak['bias_vol'] = BV
    else:
        pass
    
    if '-Trophy-Serial-' in state.keys():
        db_upload_ileak['trophy_board_name'] = state['-Trophy-Serial-']
        
    table = 'module_ileak_estimate'

    # upload
    result = run_async(upload_PostgreSQL(table_name = table, db_upload_data = db_upload_ileak))

    print(f"   >> DBTools: Uploaded leakage current estimation test of {moduleserial}!")
    
    read_table(table)

def previous_pedestal_upload(path, force=False):

    runs = glob.glob(f'{path}/pedestal_run/*')
    runs.sort()
    for run in runs:

        moduleserial = run.removeprefix(configuration["DataLoc"].rstrip('/') + '/').split('/')[0].replace('-', '')
        fname = run+'/pedestal_run0.root'

        df_data = df_from_path(run)
        if not force and pedestal_exists(moduleserial, df_data):
            continue

        density = moduleserial[4]
        shape = moduleserial[5]
        sen_thickness = moduleserial[6]
        hb_type = density+shape

        df_data = add_mapping(df_data, hb_type = hb_type)

        norm_mask, calib_mask, cm0_mask, cm1_mask, nc_mask = create_masks(df_data)

        # count dead/noisy channels
        zeros = df_data['adc_stdd'] == 0

        if ('320M' in moduleserial) and (sen_thickness is not None):
            # compromise definition from https://indico.cern.ch/event/1602073/contributions/6752482/attachments/3159554/5613107/acroberts_noise_study_oct25.pdf
            # do not ground based on these labels! definition WIP
            if density == 'H' and sen_thickness == '1': noisy_limit = 3
            elif density == 'H' and sen_thickness == '2': noisy_limit = 2.5
            elif density == 'L' and sen_thickness == '2': noisy_limit = 5
            elif density == 'L' and sen_thickness == '3': noisy_limit = 4
            else: noisy_limit = 8
        elif '320M' in moduleserial:
            noisy_limit = 8
        else:
            noisy_limit = 2
        highval = df_data['adc_stdd'] > noisy_limit

        count_bad_cells = np.sum((zeros) & (df_data["pad"] > 0)) + np.sum(highval & (df_data["pad"] > 0) & ~(calib_mask))
        list_dead_cells = df_data["pad"][zeros & (df_data["pad"] > 0)].tolist()
        list_noisy_cells = df_data["pad"][highval & (df_data["pad"] > 0) & ~(calib_mask)].tolist()

        status = None
        rundir = run.split('/')[-1]
        runtime = run_to_datetime(rundir)

        for key in statusdict.keys():
            if key.replace(' ', '_') in run:
                status = key

        # grab test configuration .yaml file and convert to json to upload
        test_config_yaml_path = run+'/initial_full_config.yaml'
        test_config = {}
        with open(test_config_yaml_path, 'r') as file:
            test_config = yaml.safe_load(file)
        test_config_json_string = json.dumps(test_config)
                
        # build upload row list
        namekey = 'module_name' if '320M' in moduleserial else 'hxb_name'
        db_upload_ped = {namekey: moduleserial,
                         'status': statusdict[status],
                         'status_desc': status,
                         'count_bad_cells': count_bad_cells,
                         'list_dead_cells': list_dead_cells,
                         'list_noisy_cells':list_noisy_cells,
                         'date_test': runtime.date(),
                         'time_test': runtime.time(),
                         'cell': df_data['pad'].tolist(), # rename pad -> cell
                         'pedestal_config_json': test_config_json_string
                         }

        dfkeys = ['chip', 'channel', 'channeltype', 'adc_median', 'adc_iqr', 'tot_median', 'tot_iqr', 'toa_median', 'toa_iqr',
                  'adc_mean', 'adc_stdd', 'tot_mean', 'tot_stdd', 'toa_mean', 'toa_stdd', 'tot_efficiency', 'tot_efficiency_error',
                  'toa_efficiency', 'toa_efficiency_error', 'x', 'y', 'corruption']
        for key in dfkeys:
            db_upload_ped[key] = df_data[key].tolist()
        db_upload_ped['corruption'] = [bool(v) for v in db_upload_ped['corruption']]

        # if live module, add the bias voltage to the row list                                                       
        if 'BV' in run and '320M' in moduleserial:
            segments = run.split('_')
            for seg in segments:
                if 'BV' in seg:
                    BV = int(seg.split('BV')[1].rstrip('\n '))
                    db_upload_ped['bias_vol'] = BV
        elif '320M' in moduleserial:
            BV = -1
            db_upload_ped['bias_vol'] = BV
        else:
            pass

        table = 'module_pedestal_test' if '320M' in moduleserial else 'hxb_pedestal_test'

        # upload
        result = run_async(upload_PostgreSQL(table_name = table, db_upload_data = db_upload_ped))
        
        print(f"   >> DBTools: Uploaded pedestal run {run} for {moduleserial}!")
        
        #read_table(table)   
        
def pedestal_exists(moduleserial, df):
    
    if '320M' in moduleserial:
        result = run_async(fetch_serial_PostgreSQL('module_pedestal_test', moduleserial))
    elif '320X' in moduleserial:
        result = run_async(fetch_serial_PostgreSQL('hxb_pedestal_test', moduleserial))

    runs = []

    for r in result:
        runs.append(r)

    for r in runs:
        if np.all(np.array(r['adc_stdd']) == np.array(df['adc_stdd'])):
           return True

    return False

def df_from_path(path):

    fname = path+'/pedestal_run0.root'
    moduleserial = path.removeprefix(configuration["DataLoc"].rstrip('/') + '/').split('/')[0].replace('-', '')
    f = uproot.open(fname)
    try:
        tree = f["runsummary"]["summary"]

        # different uproot functions for different OS =.=
        if configuration['TestingPCOpSys'] == 'Centos7':
            df_data = tree.pandas.df()
        elif configuration['TestingPCOpSys'] == 'Alma9':
            df_data = tree.arrays(library='pd')
    except:
        print("   -- DBTools: No tree found in pedestal file!")
        return 0

    density = moduleserial[4]
    shape = moduleserial[5]
    hb_type = density+shape

    df_data = add_mapping(df_data, hb_type = hb_type)

    return df_data

def iv_upload(datadict, state):
    """
    Uploads the resultant data from an IV curve. Information including the module serial is read from the state dict, but the
    IV data itself is read from the output datadict.
    """
    
    moduleserial = state['-Module-Serial-']
    data = datadict['data']
    RH = datadict['RH']
    Temp = datadict['Temp'] 

    print(f"   >> DBTools: Uploading (and saving) iv curve of {moduleserial}")
    
    # save iv as pkl file
    iv_save(datadict, state)
    
    v1 = 500
    v2 = 850
    try:
        ratio = float(data[:,2][np.argwhere(data[:,0] == v2)] / data[:,2][np.argwhere(data[:,0] == v1)])
    except:
        ratio = 0.

    comment = None
    if len(state['-Output-Subdir-'].split('/')) == 3:
        comment = state['-Output-Subdir-'].split('/')[2]

    db_upload_iv = {'module_name': moduleserial,
                    'rel_hum': str(RH),
                    'temp_c': str(Temp),
                    'status': statusdict[state['-Module-Status-']],
                    'status_desc': state['-Module-Status-'],
                    'grade': '',
                    'ratio_i_at_vs': ratio,
                    'ratio_at_vs': [float(v1), float(v2)],
                    'program_v': data[:,0].tolist(),
                    'meas_v': data[:,1].tolist(),
                    'meas_i': data[:,2].tolist(),
                    'meas_r': data[:,3].tolist(),
                    'date_test': datadict['datetime'].date(),
                    'time_test': datadict['datetime'].time(),
                    'inspector': state['-Inspector-'],
                    'comment': comment
                    }
    
    # upload
    result = run_async(upload_PostgreSQL(table_name = 'module_iv_test', db_upload_data = db_upload_iv))

    print(f"   >> DBTools: Uploaded iv curve of {moduleserial}")
    read_table('module_iv_test')

def other_test_upload(state, test_name, BV, ind=-1):

    moduleserial = state['-Module-Serial-']
    RH = state['-Box-RH-']
    Temp = state['-Box-T-']

    now = datetime.now()
    trimval = None if '-Pedestals-Trimmed-' not in state.keys() else (0. if state['-Pedestals-Trimmed-'] == True else float(state['-Pedestals-Trimmed-']))

    outdir = state['-Output-Subdir-']
    runs = glob.glob(f'{configuration["DataLoc"]}/{outdir}/{test_name}/run_*')
    runs.sort()
    thisrun = runs[ind] # most recent run by default

    os.system(f'tar -czf tar_{test_name}_{thisrun.split("/")[-1][4:]}.tgz {thisrun}')
    with open(f'tar_{test_name}_{thisrun.split("/")[-1][4:]}.tgz',"rb") as f:
        tarfile = f.read()

    comment = None
    if len(state['-Output-Subdir-'].split('/')) == 3:
        comment = state['-Output-Subdir-'].split('/')[2]

        
    db_upload_other = {'module_name': moduleserial,
                       'status': statusdict[state['-Module-Status-']],
                       'status_desc': state['-Module-Status-'],
                       'rel_hum': str(RH),
                       'temp_c': str(Temp),
                       'bias_vol': BV,
                       'trim_bias_vol': trimval,
                       'date_test': now.date(),
                       'time_test': now.time(),
                       'inspector': state['-Inspector-'],
                       'comment': comment,
                       'other_test_name': test_name,
                       'other_test_output': tarfile 
                   }

    if '320M' in moduleserial:
        if '-Leakage-Current-' in state.keys(): # add measured leakage current
            db_upload_other['meas_leakage_current'] = state['-Leakage-Current-']

    if '-Trophy-Serial-' in state.keys():
        db_upload_other['trophy_board_name'] = state['-Trophy-Serial-']
            
    # upload
    result = run_async(upload_PostgreSQL(table_name = 'mod_hxb_other_test', db_upload_data = db_upload_other))

    os.system(f'rm tar_{test_name}_{thisrun.split("/")[-1][4:]}.tgz')

    print(f"   >> DBTools: Uploaded other test of {moduleserial}")
    read_table('mod_hxb_other_test')

def plots_upload(state, ind=-1):
    """
    Uploads pedestal run plots to db for later viewing.
    """
    
    # define the path to the hexmap plots
    moduleserial = state['-Module-Serial-']
    outdir = state['-Output-Subdir-']
    hexpaths = glob.glob(f'{configuration["DataLoc"]}/{outdir}/{moduleserial}_run*_adc_mean.png')
    hexpaths.sort()
    hexpath = hexpaths[ind][:-len('_adc_mean.png')]

    print(f"   >> DBTools: Uploading pedestal plots of module {moduleserial} into database")

    # open hexmaps
    hexpaths = glob.glob(f'{hexpath}_*.png')
    for path in hexpaths:

        compress_png(path)
        
        if 'mean' in path:
            with open(path, 'rb') as f:
                hexmean = f.read()
        elif 'stdd' in path:
            with open(path, 'rb') as f:
                hexstdd = f.read()

    # find pedestal run dir
    runs = glob.glob(f'{configuration["DataLoc"]}/{outdir}/pedestal_run/*')
    runs.sort()
    dname = runs[ind] # should always be the same run

    # open plots from pedestal run dir
    noiseplots = glob.glob(dname+'/noise_vs_channel_chip*.png')
    noise = []
    for chip in noiseplots:
        with open(chip, 'rb') as f:
            noise.append(f.read())

    pedestalplots = glob.glob(dname+'/pedestal_vs_channel_chip*.png')
    pedestal = []
    for chip in pedestalplots:
        with open(chip, 'rb') as f:
            pedestal.append(f.read())
            
    totnoiseplots = glob.glob(dname+'/total_noise_chip*.png')
    totnoise = []
    for chip in totnoiseplots:
        with open(chip, 'rb') as f:
            totnoise.append(f.read())
                
    comment = None
    if len(state['-Output-Subdir-'].split('/')) == 3:
        comment = state['-Output-Subdir-'].split('/')[2]

    trimval = None if '-Pedestals-Trimmed-' not in state.keys() else (0. if state['-Pedestals-Trimmed-'] == True else float(state['-Pedestals-Trimmed-']))

    # upload the plots
    db_upload_plots = {'module_name': moduleserial,
                       'status': statusdict[state['-Module-Status-']],
                       'status_desc': state['-Module-Status-'],
                       'adc_mean_hexmap': hexmean,
                       'adc_std_hexmap': hexstdd,
                       'noise_channel_chip': noise,
                       'pedestal_channel_chip': pedestal,
                       'total_noise_chip': totnoise,
                       'trim_bias_voltage': trimval,
                       'inspector': state['-Inspector-'],
                       'comment_plot_test': comment
                       }

    result = run_async(upload_PostgreSQL(table_name = 'module_pedestal_plots', db_upload_data = db_upload_plots))

    print(f"   >> DBTools: Uploaded pedestal plots of {moduleserial}")
    
    read_table('module_pedestal_plots')

def fetch_front_wirebond(moduleserial):

    result = run_async(fetch_serial_PostgreSQL('front_wirebond', moduleserial))

    runs = []
    for r in result:
        runs.append(r)

    return runs

def fetch_module_inspect(moduleserial):

    result = run_async(fetch_serial_PostgreSQL('module_inspect', moduleserial))

    runs = []
    for r in result:
        runs.append(r)

    return runs

def fetch_proto_inspect(moduleserial):

    moduleserial = moduleserial.replace('M', 'P', 1) # protomodule serial number

    result = run_async(fetch_serial_PostgreSQL('proto_inspect', moduleserial))

    runs = []
    for r in result:
        runs.append(r)

    return runs

def fetch_comments(moduleserial):

    comments = []

    try:
        result = run_async(get_comments(moduleserial))

        for r in result:
            comments.append(r)

    except Exception:
        print('   -- DBTools comments exception; continuing:', traceback.format_exc())

    return comments

def fetch_sensor_iv(moduleserial):

    result = run_async(fetch_serial_PostgreSQL('module_info', moduleserial))

    runs = []
    for r in result:
        runs.append(r)

    thisrun = runs[-1]
    scratchpad = thisrun['sen_name'].split('_')[0]
    
    del runs

    result = run_async(fetch_serial_PostgreSQL('sen_iv_data', scratchpad))

    runs = []
    for r in result:
        runs.append(r)

    #print('actual_volts', np.array(runs[-1]['actual_volts']).shape)
    #print('tot_curnt_nanoamp', np.array(runs[-1]['tot_curnt_nanoamp']).shape)
    #print('curnt_nanoamp', np.array(runs[-1]['curnt_nanoamp']).shape)

    if len(runs) == 0:
        return None

    run = runs[-1]

    v = np.array(run['actual_volts'][0])
    curnt = np.array(run['tot_curnt_nanoamp'])
    i = np.mean(curnt, axis = 0)
    di = np.std(curnt, axis = 0)
    
    return v, i, di

# new 2026/6/25 - by-cell thresholds and masks
# all partials +1, HD Left +1 additional
# below channels +1
cells_increased_noisy_threshold = {
    'HF1': [14, 15, 16, 17],
    'HF2': None,
    'LF2': [39, 92],
    'LF3': [49, 92],
    'HT1': [99, 137],
    'HB1': None,
    'HL1': [388, 440, 441, 456, 457],
    'HR1': None,
    'LT3': None,
    'LB3': [202],
    'LL3': [11, 197, 206],
    'LR3': [97, 100, 202],
    'L53': [18],
}

# then, mask these cells completely as average noise is quite high
cells_mask = {
    'HL1': [368, 406],
    'LB3': [202],
}


def readout_info(moduleserial, modulestatus = 'Completely Encapsulated', forcecantgrade=False):

    density = moduleserial[4]
    shape = moduleserial[5]
    sen_thickness = moduleserial[6]
    hb_type = density+shape
    modtype = density+shape+sen_thickness
    
    # fetch pedestals for various bias voltages
    bv1runs = fetch_pedestal(moduleserial, 1, 300, modulestatus)
    bv2runs = fetch_pedestal(moduleserial, 2, 300, modulestatus)
    bv10runs = fetch_pedestal(moduleserial, 10, 300, modulestatus)
    bv100runs = fetch_pedestal(moduleserial, 100, 300, modulestatus)
    lowBVruns = bv1runs + bv2runs + bv10runs + bv100runs
    midBVruns = fetch_pedestal(moduleserial, 300, 300, modulestatus)
    highBVruns = fetch_pedestal(moduleserial, 500, 300, modulestatus)
    if len(highBVruns) == 0:
        highBVruns = fetch_pedestal(moduleserial, 800, 300, modulestatus)
        
    # backwards compatibility for historical modules
    if len(lowBVruns) < 1 or len(midBVruns) < 1 or len(highBVruns) < 1 and (modulestatus == 'Completely Bonded' or modulestatus == 'Completely Encapsulated'):
        status = modulestatus.replace('Completely','Frontside')
        lowBVruns = fetch_pedestal(moduleserial, 10, 300, status)
        midBVruns = fetch_pedestal(moduleserial, 300, 300, status)
        highBVruns = fetch_pedestal(moduleserial, 800, 300, status)
        if len(highBVruns) == 0:
            highBVruns = fetch_pedestal(moduleserial, 500, 300,status)

    # grab frontwirebond from DB to check grounded channels and channels that could not be bonded
    frontwirebond = fetch_front_wirebond(moduleserial)
    if len(lowBVruns) < 1 or len(midBVruns) < 1 or len(highBVruns) < 1 or len(frontwirebond) < 1 or forcecantgrade:
        if not forcecantgrade:
            print(f"   >> DBTools: cannot report readout info: lowBV {len(lowBVruns)} midBV {len(midBVruns)} high BV {len(highBVruns)} front wirebond info {len(frontwirebond)}")
        return len(lowBVruns), len(midBVruns), len(highBVruns), len(frontwirebond), False

    # choose only one of each type of run for grading
    print(f"   >> DBTools: found pedestals with BV - 1: {len(bv1runs)}, 10: {len(bv10runs)}, 100: {len(bv100runs)}, 300: {len(midBVruns)}, 500: {len(highBVruns)}")
    if len(bv1runs) >= 1 and len(bv10runs) >= 1 and len(bv100runs) >= 1:
        allruns = [bv1runs[-1]] + [bv10runs[-1]] + [bv100runs[-1]] + [midBVruns[-1]] + [highBVruns[-1]]
    else:
        allruns = lowBVruns + [midBVruns[-1]] + [highBVruns[-1]]

    # cannot grade if any grading run has corrupted channels
    for run in allruns:
        if any(np.array(run.get('corruption') or []) == 1):
            print(f"   >> DBTools: cannot report readout info: pedestal run has corrupted channels")
            return len(lowBVruns), len(midBVruns), len(highBVruns), len(frontwirebond), True

    badcell = set()

    # create masks now and then reuse
    cellid = np.array(highBVruns[-1]['cell'])
    celltype = np.array(highBVruns[-1]['channeltype'])
    norm_mask = (celltype == 0) & (cellid > 0)
    calib_mask = (celltype == 1) & (cellid > 0)
    
    if len(bv1runs) > 0 and len(bv10runs) > 0 and len(bv100runs) > 0:
        # check unbonded channels, state-of-the-art version
        bv1noise = np.array(bv1runs[-1]['adc_stdd'])
        bv10noise = np.array(bv10runs[-1]['adc_stdd'])
        bv100noise = np.array(bv100runs[-1]['adc_stdd'])
        bv1t10ratio = np.array(bv1runs[-1]['adc_stdd']) / np.array(bv10runs[-1]['adc_stdd'])
        bv10t100ratio = np.array(bv10runs[-1]['adc_stdd']) / np.array(bv100runs[-1]['adc_stdd'])

        checksum = (((bv1noise < 1.2) & (bv1noise > 0.)).astype(int)
                  + ((bv1t10ratio < 1.1) & (bv10noise > 0.) & (bv1noise < 2.)).astype(int) # bv1 noise check to catch flat noisy channels
                  + ((bv10t100ratio < 1.1) & (bv100noise > 0.) & (bv1noise < 2.)).astype(int))
        uncon = checksum >= 2 # pass at least two of three checks
        unconcells = cellid[uncon & (norm_mask | calib_mask)]
    else:
        # check unbonded channels, old version
        unbondthresh = 0.
        if '320ML' in moduleserial:
            unbondthresh = 1.7
        elif '320MH' in moduleserial:
            unbondthresh = 1.4
        unbondedrun = lowBVruns[0] # choose lowest BV run
        noise = np.array(unbondedrun['adc_stdd'])
        uncon = (noise[norm_mask | calib_mask] <= unbondthresh) & (noise[norm_mask | calib_mask] > 0.)
        unconcells = cellid[norm_mask | calib_mask][uncon]
    for cell in unconcells:
        badcell.add(cell)
        
    # check dead channels
    ldeadcells = []
    for run in allruns:
        noise = np.array(run['adc_stdd'])
        zeros = noise == 0
        deadcell = cellid[zeros & (norm_mask | calib_mask)]
        ldeadcells.append(deadcell)
    # Find intersection - ensure dead in all runs (unlike saturated channels)
    deadcells = reduce(np.intersect1d, ldeadcells)
    for cell in deadcells:
        badcell.add(cell)
    
    # check noisy channels - noisy in all highBVruns
    lnoisycells = []
    for run in highBVruns:
        # count dead/noisy channels
        if ('320M' in moduleserial) and (sen_thickness is not None):
            # compromise definition from https://indico.cern.ch/event/1602073/contributions/6752482/attachments/3159554/5613107/acroberts_noise_study_oct25.pdf
            # do not ground based on these labels! definition WIP
            if density == 'H' and sen_thickness == '1': noisy_limit = 3
            elif density == 'H' and sen_thickness == '2': noisy_limit = 2.5
            elif density == 'L' and sen_thickness == '2': noisy_limit = 5
            elif density == 'L' and sen_thickness == '3': noisy_limit = 4
            else: noisy_limit = 8
            if shape != 'F': noisy_limit += 1 # 2026/6/3 address high noise in partials
        elif '320M' in moduleserial:
            noisy_limit = 8
        else:
            noisy_limit = 2

        # per-channel thresholds elevate noisy limit to array
        if modtype == 'HL1':
            noisy_limit += 1
        noisy_limit = np.full(len(run['cell']), noisy_limit)
        if cells_increased_noisy_threshold[modtype]:
            cells_to_increase = np.isin(run['cell'], cells_increased_noisy_threshold[modtype])
            noisy_limit[cells_to_increase] += 1
        if modtype in cells_mask.keys():
            cells_to_mask = np.isin(run['cell'], cells_mask[modtype])
            noisy_limit[cells_to_mask] += 300 # mask these channels

        highval = np.array(run['adc_stdd']) > noisy_limit
        noisycell = cellid[(norm_mask | calib_mask) & highval]
        lnoisycells.append(noisycell)

    # find intersection
    noisycells = reduce(np.intersect1d, lnoisycells)
    for cell in noisycells:
        badcell.add(cell)

    # array of grounded cells
    groundedcells = np.array(frontwirebond[-1]['list_grounded_cells'])
    for cell in groundedcells:
        badcell.add(cell)

    # array of unbonded cells (according to wirebonder)
    wbunbondedcells = np.array(frontwirebond[-1]['list_unbonded_cells'])
    for cell in wbunbondedcells:
        badcell.add(cell)

    # grab leakage current info from db; will be empty list if no info
    # threshold is 30muA
    ileak_estimate = ileak_estimate_info(moduleserial, modulestatus=modulestatus)
    if len(ileak_estimate) > 0:
        # remake masks from ileak estimate to ensure order of arrays doesn't cause problems
        cellid = np.array(ileak_estimate['cell'])
        celltype = np.array(ileak_estimate['channeltype'])
        norm_mask = (celltype == 0) & (cellid > 0)
        calib_mask = (celltype == 1) & (cellid > 0)

        ileak = np.array(ileak_estimate['cell_leakage_current_mua'])
        highileakcells = cellid[ileak > 30.]
        for cell in highileakcells:
            badcell.add(cell)

        # check saturating channels - dead in high BV runs but not in low BV runs
        # removed for now b/c not the wisest way to check this
        #lowBVnoise = np.array(highBVruns[-1]['adc_stdd'])
        #highBVnoise = np.array(highBVruns[-1]['adc_stdd'])
        #saturated = (lowBVnoise != 0) & (highBVnoise == 0)
        #saturatedcells = cellid[saturated & (norm_mask | calib_mask)]

        # cells that are still dead after the inputdac scan we should call bad
        preileaknoise = np.array(ileak_estimate['noise_pre_inputdac'])
        postileaknoise = np.array(ileak_estimate['noise_post_inputdac'])
        saturatedcells = cellid[(postileaknoise == 0) & (norm_mask | calib_mask) & ~np.isin(cellid, deadcells)]
        for cell in saturatedcells:
            badcell.add(cell)

    else:
        highileakcells = np.array([])
        saturatedcells = np.array([])
            
    # remove zeros from all sets/arrays to be sure
    badcell.discard(0)
    unconcells = unconcells[unconcells != 0]
    deadcells = deadcells[deadcells != 0]
    noisycells = noisycells[noisycells != 0]
    groundedcells = groundedcells[groundedcells != 0]
    highileakcells = highileakcells[highileakcells != 0]
    saturatedcells = saturatedcells[saturatedcells != 0]

    # print info and return
    print(f'   >> DBTools: uncon {unconcells}; dead {deadcells}; noisy {noisycells}; grounded {groundedcells};')
    print(f'   >> DBTools: saturated {saturatedcells}; high Ileak {highileakcells}; all bad cells {badcell};')
    badfrac = len(badcell) / len(cellid[norm_mask | calib_mask])
    print(f'   >> DBTools: bad fraction {badfrac}')

    # union highileak and saturated for reporting 
    for cell in saturatedcells:
        if cell not in highileakcells:
            highileakcells = np.append(np.array(highileakcells, dtype=int), [cell])
    
    return unconcells, deadcells, noisycells, groundedcells, highileakcells, badcell, badfrac

def hexaboard_readout_info(hxbserial, status = 'Untaped'):
    
    untrimmedruns = hexaboard_fetch_pedestal(hxbserial, None, status)
    trimmedruns = hexaboard_fetch_pedestal(hxbserial, 0, status)

    def sortkey(run):
        dt = datetime.combine(run['date_test'], run['time_test'])
        return int(dt.strftime("%Y%m%d%H%M%S"))

    untrimmedruns.sort(key=sortkey)
    trimmedruns.sort(key=sortkey)
    
    if len(trimmedruns) < 1 or len(untrimmedruns) < 1:
        print(f'   >> DBTools: not enough pedestal tests: {status} {len(untrimmedruns)} untrimmed {len(trimmedruns)} trimmed')
        return None
    
    badcell = set()
    runs = untrimmedruns[-2:] + trimmedruns[-4:]
    
    # check dead channels
    ldeadcells = []
    for run in runs:
        noise = np.array(run['adc_stdd'])
        cellid = np.array(run['cell'])
        celltype = np.array(run['channeltype'])
        zeros = noise == 0
        norm_mask = (celltype == 0) & (cellid > 0)
        nc_mask = (celltype == 0) & (cellid < 0)
        calib_mask = (celltype == 1) & (cellid > 0)
        deadcell = cellid[zeros & (norm_mask | calib_mask)]
        ldeadcells.append(deadcell)
    # Find intersection
    # require dead in all tests, trimmed and untrimmed
    deadcells = reduce(np.intersect1d, ldeadcells)
    for cell in deadcells:
        badcell.add(cell)
    
    # check noisy channels
    lnoisycells = []
    for run in runs:
        noise = np.array(run['adc_stdd'])
        cellid = np.array(run['cell'])
        celltype = np.array(run['channeltype'])
        norm_mask = (celltype == 0) & (cellid > 0)
        nc_mask = (celltype == 0) & (cellid < 0)
        calib_mask = (celltype == 1) & (cellid > 0)
        med_norm = np.median(noise[norm_mask])
        mean_norm = np.mean(noise[norm_mask])
        std_norm = np.std(noise[norm_mask])
        noisy_limit = 2.
        # hxb standard def noise > 2 ADC counts
        noisycell = cellid[norm_mask | calib_mask][(noise[norm_mask | calib_mask]) > noisy_limit]
        lnoisycells.append(noisycell)
    # require noisy in all trimmed tests
    # maybe a bit tight but don't want to preemptively ground cells
    noisycells = reduce(np.intersect1d, lnoisycells)
    for cell in noisycells:
        badcell.add(cell)

    # remove zeros from all sets to be sure
    badcell.discard(0)
    deadcells = deadcells[deadcells != 0]
    noisycells = noisycells[noisycells != 0]
            
    print(f'   >> DBTools: dead {deadcells} noisy {noisycells}')
    return deadcells, noisycells

def iv_info(moduleserial, modulestatus = None):

    mmts_cold_iv = fetch_iv(moduleserial, 'Bolted', roomtemp=False)
    mmts_warm_iv = fetch_iv(moduleserial, 'Bolted', dry=True, roomtemp=True)
    smts_dry_iv = fetch_iv(moduleserial, 'Completely Encapsulated', dry=True, roomtemp=True)

    if len(mmts_cold_iv + mmts_warm_iv + smts_dry_iv) == 0:
        try:
            all_iv = fetch_iv_all(moduleserial)
            rh_list = [iv['rel_hum'] for iv in all_iv]
            t_list = [iv['temp_c'] for iv in all_iv]
            status_list = [iv['status_desc'] for iv in all_iv]
            print(f'   >> DBTools: no IV tests which pass criteria: RH:{rh_list} T:{t_list} Status:{status_list}')
            print(f'   >> DBTools: criteria are: status in [Completely Encapsulated, Bolted], RH < 12, 10 < T < 30')
            return None, None, None
        except Exception:
            print('   -- DBTools: iv_info exception:', traceback.format_exc())
            return None, None, None

    def iv_sortkey(run):
        dt = datetime.combine(run['date_test'], run['time_test'])
        return int(dt.strftime("%Y%m%d%H%M%S"))

    mmts_cold_iv = sorted(mmts_cold_iv, key=iv_sortkey)[-1] if len(mmts_cold_iv) > 0 else None
    mmts_warm_iv = sorted(mmts_warm_iv, key=iv_sortkey)[-1] if len(mmts_warm_iv) > 0 else None
    smts_dry_iv =  sorted(smts_dry_iv,  key=iv_sortkey)[-1] if len(smts_dry_iv) > 0  else None

    labels = ['SMTS Dry', 'MMTS Warm+Dry', 'MMTS Cold']
    three_ivs = [smts_dry_iv, mmts_warm_iv, mmts_cold_iv]
    three_i500v = [float(np.abs(np.array(iv['meas_i']))[np.abs(np.array(iv['program_v'])) == 500][0])
                   if (iv is not None and np.any(np.abs(np.array(iv['program_v'])) == 500))
                   else 0.
                   for iv in three_ivs]
    vs_100muA = [i5 >= 1e-4 for i5 in three_i500v]
    worst_i500v = max(three_i500v)

    sen_thickness = moduleserial[6]
    dep_v = 240 if sen_thickness == '3' else (110 if sen_thickness == '2' else 50)
    half_dep_v = dep_v / 2
    i_at_half_dep_v = None
    for iv in three_ivs:
        if iv is None:
            continue
        v_arr = np.abs(np.array(iv['meas_v']))
        i_arr = np.abs(np.array(iv['meas_i']))
        below_half = v_arr[v_arr <= half_dep_v]
        if len(below_half) == 0:
            continue
        closest_v = below_half.max()
        i_val = float(i_arr[v_arr == closest_v][0])
        if i_at_half_dep_v is None or i_val > i_at_half_dep_v:
            i_at_half_dep_v = i_val
    if i_at_half_dep_v is not None:
        print(f'   >> DBTools: I({half_dep_v:.0f}V) = {i_at_half_dep_v*1e6:.3f}uA')
    else:
        print(f'   >> DBTools: no data at or below {half_dep_v:.0f}V (half depletion)')

    # check for ohmic/bad IVs and choose worst one if present
    if any(vs_100muA):
        if any([i5 >= 0.98e-3 for i5 in three_i500v]): # hits 1mA limit
            print(f'   >> DBTools: hits 1mA limit')
            return worst_i500v, None, i_at_half_dep_v
        else:
            print(f'   >> DBTools: max I(500V) = {worst_i500v*1e6:.3f}uA is high, reporting')
            return worst_i500v, None, i_at_half_dep_v

    i_500v = None
    i_850v500v = None
    used = None

    # progressively check smts dry, mmts warm, mmts cold IVs to see if they can be
    # used for grading. return IV info from "best" IV method
    for iv, label in zip(three_ivs, labels):
        if iv is not None: # IV is present
            v = np.abs(np.array(iv['program_v']))
            i = np.abs(np.array(iv['meas_i']))
            if np.max(v) >= 500: # IV is good
                i_500v = i[abs(v) == 500][0]
                print(f'   >> DBTools: {label} I(500V) = {i_500v*1e6:.3f}uA')
                used = label
                
    # for only mmts_cold_iv, find I(850V)/I(500V) and return (currently unused but was in the past)
    if mmts_cold_iv is not None: # cold MMTS IV is present
        v = np.abs(np.array(mmts_cold_iv['program_v']))
        i = np.abs(np.array(mmts_cold_iv['meas_i']))
        if np.max(v) >= 850: # cold MMTS IV is complete
            i_500v = i[abs(v) == 500][0]
            i_850v = i[abs(v) == 850][0]
            i_850v500v = i_850v / i_500v

    if i_850v500v is not None:
        print(f'   >> DBTools: reporting {used} I(500V) = {i_500v*1e6:.3f}uA; I(850V)/I(500V) = {i_850v500v:.3f}')
    elif i_500v is not None:
        print(f'   >> DBTools: reporting {used} I(500V) = {i_500v*1e6:.3f}uA')
    else:
        print(f'   >> DBTools: no IV with V >= 500 found')
    return i_500v, i_850v500v, i_at_half_dep_v
    
def ileak_estimate_info(moduleserial, modulestatus = 'Completely Encapsulated'):

    ileak_estimates = fetch_ileak_estimate(moduleserial, 500, modulestatus)
    if len(ileak_estimates) < 1:
        print(f'   >> DBTools: no ileak estimate tests')
        return []
    ileak_estimate = ileak_estimates[-1]
    return ileak_estimate

def assembly_info(moduleserial, forcecantgrade=False):

    moduleins = fetch_module_inspect(moduleserial)
    protoins = fetch_proto_inspect(moduleserial)

    if len(moduleins) < 1 or len(protoins) < 1 or forcecantgrade:
        if not forcecantgrade:
            print(f'   >> DBTools: no assembly info')
        return len(protoins), len(moduleins)

    return protoins[-1]['avg_thickness'], protoins[-1]['flatness'], protoins[-1]['x_offset_mu'], protoins[-1]['y_offset_mu'], protoins[-1]['ang_offset_deg'], moduleins[-1]['avg_thickness'], moduleins[-1]['flatness'], moduleins[-1]['x_offset_mu'], moduleins[-1]['y_offset_mu'], moduleins[-1]['ang_offset_deg'], protoins[-1]['max_thickness'], moduleins[-1]['max_thickness']

def summary_upload(moduleserial, qc_summary):

    if qc_summary is None:
        return

    qc_summary.pop('comments', None)
    
    result = run_async(upload_PostgreSQL(table_name = 'module_qc_summary', db_upload_data = qc_summary))

    print(f"   >> DBTools: Uploaded to qc summary table for {moduleserial}")
    #ead_table('module_qc_summary')

def upload_bonding_instructions(moduleserial, list_rebond=[], list_dead_ground=[], list_noisy_ground=[]):

    result = run_async(add_bonding_instructions(moduleserial, list_rebond=list_rebond, list_dead_ground=list_dead_ground, list_noisy_ground=list_noisy_ground))

    print(f"   >> DBTools: Uploaded rebonding instructions for {moduleserial}")

    
def add_RH_T(state, force=False):
    """
    Adds RH, T inside box to the state dictionary as integers. Uses AirControl class which was implemented for CMU and is not
    general to all MACs. Automatic sensing is disabled by "HasRHSensor: false" in the configuration file.
    """
    
    RH = None
    Temp = None
    
    if ('-Box-RH-' not in state.keys() or '-Box-T-' not in state.keys()) or force: # only add once per testing session, except if you really need

        # if no automatic RH sensor, enter manually
        if not configuration['HasRHSensor'] or state['-Debug-Mode-']: 

            defaultRH = 25 if '-Box-RH-' not in state.keys() else state['-Box-RH-']
            defaultT = 22 if '-Box-T-' not in state.keys() else state['-Box-T-']

            layout = [[sg.Text('Enter current humidity and temperature:', font=('Arial', 30))],
                      [sg.Combo(list(range(0, 60)), default_value=defaultRH, key='-RH-'), sg.Text("% RH"), 
                       sg.Combo(list(range(-40, 30)), default_value=defaultT, key='-Temp-'), sg.Text(" deg C")],
                      [sg.Button('Enter')]]
            window = sg.Window(f"Module Test: Enter RH and Temp", layout, margins=(200,100))
        
            while True:
                event, values = window.read()
                if event == 'Enter' or event == sg.WIN_CLOSED:
                    RH = str(values['-RH-']).rstrip()
                    Temp = str(values['-Temp-']).rstrip()
                if RH is None or Temp is None:
                    continue
                else:
                    break

            window.close()

        # if automatic RH sensor, query for RH and T
        else:
            from AirControl import AirControl
            for i in range(10):
                controller = AirControl()
                try:
                    RH = controller.get_humidity()
                    Temp = controller.get_temperature()
                    break
                except Exception:
                    print('     -- RH/T exception:', traceback.format_exc())
                    print(f'     -- Trying again (attempt {i})')

            print(f'     >> RH/T: measured RH={RH}%; T={Temp}ºC')

        try:
            state['-Box-RH-'] = int(RH)
            state['-Box-T-'] = int(Temp)
        except ValueError:
            add_RH_T(state, force)
        
        return RH, Temp

    # if no update, return state values
    else:
        return state['-Box-RH-'], state['-Box-T-']


from PIL import Image
def compress_png(image_path):
    """Compress image before uploading to DB
    """
    img = Image.open(image_path)
    img = img.convert("P", palette=Image.ADAPTIVE, colors=256) # limit the colors
    img.save(image_path, optimize=True)
    print("     >> DBTools: Image compressed")

def create_trophy_mezzanine(trophyserial, mezzserial, comment=None, station='Single-Module Test Stand', status='in_use'):

    db_upload_trophy = {'trophy_name': trophyserial,
                        'mezzanine_name': mezzserial,
                        'station_name': station,
                        'status': status,
                        'comment': comment,
                        'count_errors': 0,
                        'count_uses': 0,
                        'start_use_timestamp': datetime.now(),
                        }

    result = run_async(upload_PostgreSQL('trophy_and_mezzanine_boards', db_upload_trophy))

def increment_trophy_uses(station='Single-Module Test Stand'):
    """
    Increments trophy and mezzanine table count_uses field
    Assumes one entry for this station with status == 'in_use'
    """

    result = run_async(fetch_trophy_mezz(station=station))

    # if more than one trophy in use, exit
    # is this the right thing to do?
    if len(result) > 1:
        print(f'   >> DBTools: more than one trophy in use for station {station}')
        return
    
    res = result[0]
    trophy = res['trophy_name']
    mezz = res['mezzanine_name']
    n_uses = res['count_uses']
    
    result = run_async(modify_trophy_mezz(trophy, 'count_uses', n_uses+1))

def increment_trophy_errors(station='Single-Module Test Stand'):
    """
    Increments trophy and mezzanine table count_errors field
    Assumes one entry for this station with status == 'in_use'
    """

    result = run_async(fetch_trophy_mezz(station=station))

    # if more than one trophy in use, exit
    # is this the right thing to do?
    if len(result) > 1:
        print(f'   >> DBTools: more than one trophy in use for station {station}')
        return
    
    res = result[0]
    trophy = res['trophy_name']
    mezz = res['mezzanine_name']
    n_errors = res['count_errors']
    
    result = run_async(modify_trophy_mezz(trophy, 'count_errors', n_errors+1))

def swap_trophy_mezz(new_trophyserial, new_mezzserial, station='Single-Module Test Stand'):
    """
    Swaps trophy and mezzanine set by setting previous entry to have status == 'used'
    and either creating a new entry with status == 'in_use' or modifying existing entry
    """

    # fetch current trophy and mezz
    result = run_async(fetch_trophy_mezz(station=station))

    # if more than one trophy in use, exit
    # is this the right thing to do?
    if len(result) > 1:
        print(f'   >> DBTools: more than one trophy in use for station {station}')
        return
    elif len(result) == 1: # one trophy in use
        res = result[0]
        trophy = res['trophy_name']
        mezz = res['mezzanine_name']

        # set it to status 'used'
        result = run_async(modify_trophy_mezz(trophy, 'status', 'used'))
    else: # no trophies at this station
        pass # do nothing?

    # check if new trophy exists
    result = run_async(fetch_trophy_mezz(trophyserial = new_trophyserial))

    if len(result) >= 1: # trophy exists
        result = run_async(modify_trophy_mezz(new_trophyserial, 'status', 'in_use'))
        result = run_async(modify_trophy_mezz(new_trophyserial, 'station_name', station))
        result = run_async(modify_trophy_mezz(new_trophyserial, 'mezzanine_name', new_mezzserial))
        
    else: # trophy does not exist
        create_trophy_mezzanine(new_trophyserial, new_mezzserial, station=station, status='in_use')

def get_trophy_mezz(station):

    # fetch current trophy and mezz
    result = run_async(fetch_trophy_mezz(station=station))
    
    # if more than one trophy in use, exit
    # is this the right thing to do?
    if len(result) > 1:
        print(f'   >> DBTools: more than one trophy in use for station {station}')
        return
    elif len(result) == 0:
        print(f'   >> DBTools: no trophy in use for station {station}')
        return
    else:
        return result[0]['trophy_name'], result[0]['mezzanine_name'], result[0]['count_uses']
    
def fetch_module_qc_summary(moduleserial):
    """
    Returns the most recent entry in the module_qc_summary table in the local database for the module of the given name. 
    """
    
    result = run_async(fetch_PostgreSQL('module_qc_summary', part_name=moduleserial))

    if len(result) >= 1:
        return result[0]
    else:
        return None
