"""Stream bounded parallel SSH pipes through Windows RAM, without local bulk files."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shlex
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--backup', type=Path, required=True)
parser.add_argument('--name', required=True)
parser.add_argument('--source-host', required=True)
parser.add_argument('--source-work', required=True)
parser.add_argument('--hpc-config', type=Path, required=True)
parser.add_argument('--hpc-root', required=True)
args = parser.parse_args()
backup = args.backup.resolve(strict=True)
receipt = json.loads((backup / (args.name + '.sealed.json')).read_text())
name = receipt['name']
assert name == args.name and name.replace('-', '').isalnum()
source = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ClearAllForwardings=yes', '-o', 'ConnectTimeout=45', args.source_host]
proxy = 'ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ClearAllForwardings=yes -o ConnectTimeout=45 -W %h:%p ' + args.source_host
hpc = ['ssh', '-F', str(args.hpc_config.resolve(strict=True)), '-o', 'ConnectTimeout=120', '-o', 'ProxyCommand=' + proxy, 'starlight-c']
root = args.hpc_root
assert root.startswith('/XYFS02/HDD_POOL/sysu_pww/sysu_pww_2/dsh-simulation/inputs/')
python = '/APP/u22/x86/anaconda3/202309/bin/python3'
chunk = 256 * 1024**2
partial = root + '/archives/' + receipt['cipher_file'] + '.partial'
initial = ('import pathlib,json; p=pathlib.Path(' + repr(partial) + '); t=p.with_suffix(""); '
           'f=None if t.exists() else p.open("a+b"); '
           '(f.truncate(' + str(receipt['cipher_bytes']) + '),f.close()) if f is not None else None')
def remote_check(command):
    for attempt in range(8):
        result = subprocess.run(hpc + [command], timeout=240)
        if result.returncode == 0:
            return
        print(json.dumps({'phase': 'control-connection-retry', 'attempt': attempt + 1}), flush=True)
        time.sleep(min(5 * (attempt + 1), 30))
    raise RuntimeError('HPC control connection failed')


remote_check(python + ' -c ' + shlex.quote(initial))


def relay(number):
    offset = number * chunk
    size = min(chunk, receipt['cipher_bytes'] - offset)
    marker = root + '/logs/' + ('%s.range-%012d.json' % (name, offset))
    prior = subprocess.run(hpc + ['test -f ' + shlex.quote(marker)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=240)
    if prior.returncode == 0:
        print(json.dumps({'phase': 'range-already-present', 'offset': offset}), flush=True)
        return
    command = 'dd if=' + shlex.quote(args.source_work + '/' + receipt['cipher_file']) + ' bs=1048576 iflag=skip_bytes,count_bytes skip=' + str(offset) + ' count=' + str(size) + ' status=none'
    receiver = shlex.join([python, root + '/tools/receive_archive_range_hpc.py', '--root', root, '--name', name, '--offset', str(offset), '--size', str(size)])
    for attempt in range(8):
        with (backup / ('%s.range-%02d.log' % (name, number))).open('ab') as log:
            producer = subprocess.Popen(source + [command], stdout=subprocess.PIPE, stderr=log)
            consumer = subprocess.Popen(hpc + [receiver], stdin=producer.stdout, stdout=log, stderr=log)
            producer.stdout.close()
            try:
                received = consumer.wait(timeout=1800)
                sent = producer.wait(timeout=60)
            except subprocess.TimeoutExpired:
                consumer.kill()
                producer.kill()
                consumer.wait()
                producer.wait()
                received = sent = -1
        if received == sent == 0:
            print(json.dumps({'phase': 'range-transferred', 'offset': offset, 'bytes': size}), flush=True)
            return
        time.sleep(min(5 * (attempt + 1), 30))
    raise RuntimeError('Range transfer failed: ' + str(offset))


with ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(relay, range((receipt['cipher_bytes'] + chunk - 1) // chunk)))
final = ('import pathlib,json; r=pathlib.Path(' + repr(root) + '); n=' + repr(name) + '; '
         'v=json.loads((r/"logs"/(n+".sealed.json")).read_text()); '
         'p=r/"archives"/(v["cipher_file"]+".partial"); t=r/"archives"/v["cipher_file"]; '
         'assert t.exists() or p.exists(); p.rename(t) if not t.exists() else None; p=t; '
         'assert p.stat().st_size==v["cipher_bytes"]; p.chmod(0o600); '
         'v.update(phase="transferred-awaiting-compute-node-verification",hpc_archive_path=str(p)); '
         '(r/"logs"/(n+".transfer.json")).write_text(json.dumps(v,indent=2))')
remote_check(python + ' -c ' + shlex.quote(final))
print(json.dumps({'phase': 'transferred-awaiting-compute-node-verification', 'name': name}), flush=True)
