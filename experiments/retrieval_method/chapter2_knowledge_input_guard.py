"""Python-level QA/construction input isolation; no OS sandbox claim."""
import os
from pathlib import Path
import sys

def install(public_question_file=None,*,public_question_files=None):
    if public_question_file is not None and public_question_files is not None:raise ValueError('Use one exact-file allowlist')
    paths=public_question_files if public_question_files is not None else ([public_question_file] if public_question_file else [])
    allowed={Path(p).resolve() for p in paths}
    blocked={'scoring','authoring','review','evaluation_only','data_design','local_private'}
    def hook(event,args):
        if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0])).resolve()
            parts={s.casefold() for s in path.parts}
            if blocked&parts or path.name.casefold() in {'annotations.json','evidence.json','candidate-inventory.json','split.json'}:
                raise PermissionError('production process cannot read gold, authoring or split metadata')
            if 'graduation-datasets' in parts and path not in allowed:
                raise PermissionError('only the selected id/question file is a production dataset input')
        if event in {'os.system','subprocess.Popen'}:
            raise PermissionError('production process cannot launch a subprocess')
    sys.addaudithook(hook)
    return {'python_audit_hook':True,'gold_and_authoring_disabled':True,'dataset_input':'exact_selected_id_question_file_only',
      'subprocess_disabled':True,'limits':'Python implementation guard, not an operating-system sandbox.'}
