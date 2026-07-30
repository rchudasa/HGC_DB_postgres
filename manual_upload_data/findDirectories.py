import json
import os
import glob

def getModuleName(path):
    moduleDirName = path.split('/')[-1]
    moduleName = moduleDirName.replace('-', '') if '-' in moduleDirName else moduleDirName
    if moduleName.startswith('320'):
        return moduleName[0:15]

def checkROCVersion(path):
    moduleDirName = path.split('/')[-1]
    moduleName = moduleDirName.replace('-', '') if '-' in moduleDirName else moduleDirName
    rocVersion = moduleName[8:9]
    #print("modulename type", type(moduleName))
    return rocVersion 

def getDirList(path):
    dirList = []
    for file in glob.glob(f'{path}/*'):
        if os.path.isdir(file) and 'data' in file:
            dirList.append(file)
    finalDirList = []
    moduleNames = []
    for dir in dirList:
        for ped_dir in glob.glob(dir+'/*'):
            if os.path.isdir(ped_dir) and '320' in ped_dir: 
                checkROCVersion(ped_dir)
                if checkROCVersion(ped_dir)  in ['2', '4', 'B', 'C', 'D']:
                    #print(f"Pedestal Directory:{ped_dir}")
                    finalDirList.append(ped_dir)
                    moduleNames.append(getModuleName(ped_dir))
                    #print(f"Ped dir:{ped_dir} , Module Names:{getModuleName(ped_dir)}")
    return zip(finalDirList, moduleNames)

uploadPedestal_DirList = getDirList('/home/rchudasa/module_test/hexactrl-script/')
#uploadIV_DirList = getDirList('/home/rchudasa/bias_supply_monitor/')

#print(list(uploadPedestal_DirList))