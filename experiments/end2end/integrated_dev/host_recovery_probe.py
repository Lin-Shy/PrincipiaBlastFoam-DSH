"""Three bounded, serial native boots with concurrent read-only host sampling."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from start import HERE, WS, prepare, runtime_node, common_environment

SAMPLE = r'''
$os = Get-CimInstance Win32_OperatingSystem
$processes = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in @('git','node','python','pwsh','powershell') } | ForEach-Object {
    [pscustomobject]@{pid=$_.Id;name=$_.ProcessName;working_set_bytes=$_.WorkingSet64;private_bytes=$_.PrivateMemorySize64}
})
[pscustomobject]@{utc=(Get-Date).ToUniversalTime().ToString('o');total_physical_kib=$os.TotalVisibleMemorySize;free_physical_kib=$os.FreePhysicalMemory;total_virtual_kib=$os.TotalVirtualMemorySize;free_virtual_kib=$os.FreeVirtualMemory;processes=$processes} | ConvertTo-Json -Depth 4 -Compress
'''


def main():
    destination = Path(sys.argv[1]).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    runtime = WS / '.chapter3-runtime/stage-20261117/dsh'
    template = WS / 'graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/openfoam_cavity_revision100_20261122/old/professional'
    stop = threading.Event()
    samples = []
    def sample():
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', SAMPLE],
            capture_output=True, text=True, timeout=15)
        row = json.loads(result.stdout) if result.returncode == 0 else {'sample_error': result.returncode}
        samples.append(row)
        with (destination / 'memory.jsonl').open('a', encoding='utf8') as out:
            out.write(json.dumps(row) + '\n')
    sample()
    def monitor():
        while not stop.wait(2):
            try:
                sample()
            except Exception as error:
                samples.append({'sample_error': type(error).__name__})
    thread = threading.Thread(target=monitor)
    thread.start()
    rounds = []
    try:
        for number in range(1, 4):
            root = destination / f'round{number}'
            for folder in ('workspace', 'home', 'agents_home', 'skills', 'user', 'tmp', 'cache'):
                (root / folder).mkdir(parents=True, exist_ok=False)
            (root / 'dump.yml').write_text((template / 'dump.yml').read_text(encoding='utf8').replace(str(template), str(root)), encoding='utf8')
            started = time.time()
            prepare(root, runtime)
            env = common_environment(root)
            env.update(C3_RUNTIME=str(runtime), C3_PYTHON=sys.executable, C3_MODULE_PATH=str(HERE.parent))
            with (root / 'stdout.log').open('x') as out, (root / 'stderr.log').open('x') as err:
                result = subprocess.run([runtime_node(runtime), str(HERE / 'host_recovery_probe.mjs'), str(runtime), str(root)],
                    cwd=root / 'workspace', env=env, stdout=out, stderr=err, timeout=90)
            probe = root / 'workspace/host-probe.json'
            rounds.append({'round': number, 'exit_code': result.returncode,
                'elapsed_seconds': time.time() - started,
                'passed': result.returncode == 0 and probe.exists() and json.loads(probe.read_bytes())['passed']})
            print(json.dumps(rounds[-1]), flush=True)
            if not rounds[-1]['passed']:
                break
    finally:
        stop.set()
        thread.join(timeout=20)
        sample()
        valid = [row for row in samples if 'free_physical_kib' in row]
        summary = {'rounds': rounds, 'all_three_passed': len(rounds) == 3 and all(row['passed'] for row in rounds),
            'samples': len(samples), 'sample_errors': len(samples) - len(valid),
            'min_free_physical_gib': min(row['free_physical_kib'] for row in valid) / 1048576,
            'min_free_virtual_gib': min(row['free_virtual_kib'] for row in valid) / 1048576,
            'max_git_process_count': max(sum(proc['name'] == 'git' for proc in row['processes']) for row in valid),
            'model_calls': 0, 'node_jobs': 0, 'stress_test': False, 'oom_root_cause_proven': False}
        (destination / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
        print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
