import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parent


def workspace(tmp_path, professional):
    common = tmp_path/"common"
    common.mkdir()
    delivery = tmp_path/"delivery"
    delivery.mkdir()
    shutil.copyfile(SOURCE/"pipe_client.py",common/"pipe_client.py")
    shutil.copyfile(SOURCE.parent/"pipe_flow/pipe_client.py",common/"pipe_schema.py")
    if professional:
        shutil.copyfile(SOURCE/"pipe_preflight.py",common/"pipe_preflight.py")
    return delivery,common/"pipe_client.py"


def write_case(directory,rhs):
    rows = [[i*.01/64,-1,2,-1,rhs] for i in range(65)]
    rows[0][1:]=[0,1,-1,0]
    rows[-1][1:]=[0,1,0,0]
    (directory/"case.json").write_text(json.dumps({"rows":rows}),encoding="ascii")


@pytest.mark.parametrize("professional",[False,True])
def test_subdirectory_submission_is_visible_once(tmp_path,professional):
    directory,client = workspace(tmp_path,professional)
    write_case(directory,1)
    subprocess.run([sys.executable,str(client),"submit"],cwd=directory,check=True)
    assert (tmp_path/"pipe_exchange/request.json").is_file()
    assert not (directory/"pipe_exchange").exists()
    duplicate = subprocess.run([sys.executable,str(client),"submit"],cwd=directory,capture_output=True)
    assert duplicate.returncode != 0


def test_failed_direction_check_does_not_consume_submission(tmp_path):
    directory,client = workspace(tmp_path,True)
    write_case(directory,-1)
    wrong = subprocess.run([sys.executable,str(client),"submit"],cwd=directory,capture_output=True)
    assert wrong.returncode != 0 and b"forcing orientation" in wrong.stderr
    assert not (tmp_path/"pipe_exchange/request.json").exists()
    write_case(directory,1)
    subprocess.run([sys.executable,str(client),"submit"],cwd=directory,check=True)
