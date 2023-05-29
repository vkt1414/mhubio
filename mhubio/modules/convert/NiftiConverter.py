"""
-------------------------------------------------
MHub - Nifti Conversion Module
-------------------------------------------------

-------------------------------------------------
Author: Leonard Nürnberg
Email:  leonard.nuernberg@maastrichtuniversity.nl
-------------------------------------------------
"""

from enum import Enum
from typing import List

from mhubio.core import Module, Instance, InstanceDataCollection, InstanceData, DataType, FileType, CT
from mhubio.core.IO import IO

import os, subprocess
import pyplastimatch as pypla # type: ignore

class NiftiConverterEngine(Enum):
    PLASTIMATCH = 'plastimatch'
    DCM2NIIX     = 'dcm2niix'

@IO.Config('engine', NiftiConverterEngine, 'plastimatch', factory=NiftiConverterEngine, the='engine to use for conversion')
@IO.Config('allow_multi_input', bool, False, the='allow multiple input files')
@IO.Config('targets', List[DataType], ['dicom:mod=ct', 'nrrd:mod=ct'], factory=IO.F.list(DataType.fromString), the='target data types to convert to nifti')
@IO.Config('bundle_name', str, 'nifti', the="bundle name converted data will be added to")
@IO.Config('converted_file_name', str, '[basename].nii.gz', the='name of the converted file')
@IO.Config('overwrite_existing_file', bool, False, the='overwrite existing file if it exists')
#@IO.Config('wrap_output', bool, False, the='Wrap output in bundles. Required, if multiple input data is allowed that is not yet separated into distinct bundles.')
class NiftiConverter(Module):
    """
    Conversion module. 
    Convert instance data from dicom or nrrd to nifti.
    """

    engine: NiftiConverterEngine
    allow_multi_input: bool
    targets: List[DataType]
    bundle_name: str                    # TODO optional type declaration
    converted_file_name: str
    overwrite_existing_file: bool
    #wrap_output: bool

    def setTarget(self, target: DataType) -> None:
        self.targets.append(target)

    def plastimatch(self, instance: Instance, in_data: InstanceData, out_data: InstanceData, log_data: InstanceData) -> None:

        #print("[DRY RUN] plastimatch")
        #print("[DRY RUN] in:  ", in_data.abspath)
        #print("[DRY RUN] out: ", out_data.abspath)
        #print("[DRY RUN] log: ", log_data.abspath)
        #return

        # set input and output paths later passed to plastimatch
        convert_args_ct = {
            "input" : in_data.abspath,
            "output-img" : out_data.abspath
        }

        # remove old log file if it exist
        if os.path.isfile(log_data.abspath): 
            os.remove(log_data.abspath)
        
        # run conversion using plastimatch
        pypla.convert(
            verbose=self.verbose,
            path_to_log_file=log_data.abspath,
            **convert_args_ct
        )

        if os.path.isfile(log_data.abspath):
            log_data.confirm()

    def dcm2nii(self, instance: Instance, in_data: InstanceData, out_data: InstanceData) -> None:

        #print("[DRY RUN] dcm2nii")
        #print("[DRY RUN] in:  ", in_data.abspath)
        #print("[DRY RUN] out: ", out_data.abspath)
        #return

        # verbosity level
        # TODO: once global verbosity levels are implemented, propagate them here
        if self.config.debug: 
            verbosity = 2
        elif self.config.verbose: 
            verbosity = 1
        else:
            verbosity = 0

        # get folder and file name as dcm2niix takes two separate arguments
        assert out_data.abspath.endswith(".nii.gz")
        out_data_dir = os.path.dirname(out_data.abspath)
        out_data_file = os.path.basename(out_data.abspath)[:-7]

        # build command
        # manual: https://www.nitrc.org/plugins/mwiki/index.php/dcm2nii:MainPage#General_Usage
        bash_command  = ["dcm2niix"]
        bash_command += ["-o", out_data_dir]        # output folder
        bash_command += ["-f", out_data_file]       # output file name (pattern, but we handle a single dicom series as input)
        bash_command += ["-v", str(verbosity)]      # verbosity
        bash_command += ["-z", "y"]                 # output compression      
        bash_command += ["-b", "n"]                 # do not generate a Brain Imaging Data Structure file      
        bash_command += [in_data.abspath]           # input folder (dicom) 

        # print run
        # TODO: implement global verbosity levels. This is required for debugging and has educational value.
        self.v(">> run: ", " ".join(bash_command))

        # execute command
        _ = subprocess.run(bash_command, check = True, text = True)

    @IO.Instance()
    @IO.Inputs('in_datas', IO.C('targets'), the="data to be converted")
    @IO.Outputs('out_datas', path=IO.C('converted_file_name'), dtype='nifti', data='in_datas', bundle=IO.C('bundle_name'), auto_increment=True, the="converted data")
    @IO.Outputs('log_datas', path='[basename].pmconv.log', dtype='log:log-task=conversion', data='in_datas', bundle=IO.C('bundle_name'), auto_increment=True, the="log generated by conversion engine")
    def task(self, instance: Instance, in_datas: InstanceDataCollection, out_datas: InstanceDataCollection, log_datas: InstanceDataCollection, **kwargs) -> None:

        # some sanity checks
        assert isinstance(in_datas, InstanceDataCollection)
        assert isinstance(out_datas, InstanceDataCollection)
        assert len(in_datas) == len(out_datas)
        assert len(in_datas) == len(log_datas)

        # filtered collection must not be empty
        if len(in_datas) == 0:
            print(f"CONVERT ERROR: no data found in instance {str(instance)}.")
            return None

        # check if multi file conversion is enables
        if not self.allow_multi_input and len(in_datas) > 1:
            print("WARNING: found more than one matching file but multi file conversion is disabled. Only the first file will be converted.")
            in_datas = InstanceDataCollection([in_datas.first()])

        # conversion step
        for i, in_data in enumerate(in_datas):
            out_data = out_datas.get(i)
            log_data = log_datas.get(i)

            # check if output data already exists
            if os.path.isfile(out_data.abspath) and not self.overwrite_existing_file:
                print("CONVERT ERROR: File already exists: ", out_data.abspath)
                continue

            # check datatype 
            if in_data.type.ftype == FileType.DICOM:

                # for dicom data use either plastimatch or dcm2niix 
                if self.engine == NiftiConverterEngine.PLASTIMATCH:
                    self.plastimatch(instance, in_data, out_data, log_data)
                elif self.engine == NiftiConverterEngine.DCM2NIIX:
                    self.dcm2nii(instance, in_data, out_data)
                else:
                    raise ValueError(f"CONVERT ERROR: unknown engine {self.engine}.")
                
            elif in_data.type.ftype == FileType.NRRD:

                # for nrrd files use plastimatch
                self.plastimatch(instance, in_data, out_data, log_data)