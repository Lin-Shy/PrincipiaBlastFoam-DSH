"""Minimal offline goal/configuration/collection/delivery workflow.

Generates sampling configuration drafts and replays existing native pressure only.
Never invokes OpenFOAM, SSH, a model, or a scientific success scorer.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import time

try:
    from .pressure_observations import read_scalar_probes, window, metrics
except ImportError:
    from pressure_observations import read_scalar_probes, window, metrics

SUPPORTED = {"peak_overpressure_pa", "sampled_peak_time_s", "whole_window_positive_area_pa_s"}


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sampling_plan(task):
    sensors = task["sensors"]
    kind = task["sampling_kind"]
    if kind not in {"point_static", "patch_static"}:
        raise ValueError("Unsupported sampling semantics")
    points = []
    for s in sensors:
        xyz = s["position_m"]
        if len(xyz) != 3 or not all(math.isfinite(x) for x in xyz):
            raise ValueError("Invalid sensor coordinate")
        points.append("("+" ".join(format(x,".12g") for x in xyz)+")")
    if kind == "patch_static":
        patch = task["patch"]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", patch):
            raise ValueError("Unsafe patch identifier")
        selector = "type patchProbes; patchName "+patch+";"
    else:
        if task.get("interpolation") != "cellPoint":
            raise ValueError("Only explicitly specified cellPoint is supported")
        selector = "type probes; interpolationScheme cellPoint;"
    fragment = 'goalPressure { '+selector+' libs ("libsampling.so"); fields (p);\n'
    fragment += "probeLocations ("+" ".join(points)+"); writeControl timeStep; writeInterval 1; }\n"
    return {"functions_fragment": fragment, "required_end_time_s": task["required_window_s"][1],
            "sensor_order": [s["id"] for s in sensors], "sensor_positions_m": [s["position_m"] for s in sensors],
            "field": "p", "unit": "Pa", "pressure_kind": "absolute_static",
            "status": "draft_not_executed", "changes_solver_or_physics": False}


def read_header(path):
    result = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.startswith("#"):
                break
            match = re.match(r"# Probe (\d+)\s+\(([^)]+)\)", line)
            if match:
                i = int(match[1])
                if i in result:
                    raise ValueError("Duplicate probe index")
                result[i] = [float(x) for x in match[2].split()]
    return result


class Workflow:
    def __init__(self, input_root, output_root, *, cache=False, goal_state=False, final_check=True):
        self.input_root = Path(input_root).resolve()
        self.output_root = Path(output_root).resolve()
        self.output_root.mkdir(parents=True, exist_ok=False)
        self.cache_enabled, self.goal_state, self.final_check = cache, goal_state, final_check
        self.memo, self.previous, self.stage_state = {}, {}, {}
        self.cost = Counter()

    def cached(self, stage, key, action):
        cache_key = (stage, key)
        if self.goal_state and stage in self.stage_state and self.stage_state[stage][0]==key:
            self.cost[stage+"_dispatch_skips"] += 1
            return self.stage_state[stage][1]
        # Legacy counter name: entries into the tool-cache layer after the state
        # guard, NOT total Python method calls, external tool calls, or LLM calls.
        self.cost[stage+"_tool_calls"] += 1
        if self.cache_enabled and cache_key in self.memo:
            self.cost[stage+"_cache_hits"] += 1
            result = self.memo[cache_key]
        else:
            self.cost[stage+"_evaluations"] += 1
            result = action()
            if self.cache_enabled:
                self.memo[cache_key] = result
        if self.goal_state:
            self.stage_state[stage]=(key,result)
        return result

    def run(self, task, query, source, expected_sha256):
        started = time.perf_counter()
        before = self.cost.copy()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",query["id"]):
            raise ValueError("Unsafe query identifier")
        source = Path(source).resolve()
        if not source.is_relative_to(self.input_root) or not source.is_file():
            raise ValueError("Source outside the explicit input root")
        raw = source.read_bytes()
        self.cost["source_hash_reads"] += 1
        self.cost["source_bytes_read"] += len(raw)
        sha = hashlib.sha256(raw).hexdigest()
        if sha != expected_sha256:
            raise ValueError("Raw source changed; no cache may override this check")
        if query["window_s"][0] < task["required_window_s"][0] or query["window_s"][1] > task["required_window_s"][1]:
            raise ValueError("Diagnostic query extends outside the declared task")
        plan_key = identity({k:task.get(k) for k in ["sensors","sampling_kind","patch","interpolation","required_window_s"]})
        plan = self.cached("configuration", plan_key, lambda:sampling_plan(task))
        def collect():
            self.cost["source_bytes_read"] += source.stat().st_size
            return read_scalar_probes(source), read_header(source)
        rows, header = self.cached("collection", sha, collect)
        association_key=identity([sha,plan_key])
        def associate():
            mapping={}
            for sensor in task["sensors"]:
                candidates = [i for i, xyz in header.items() if len(xyz)==3 and math.dist(xyz,sensor["position_m"]) < 1e-10]
                mapping[sensor["id"]] = candidates[0] if len(candidates)==1 else None
            return mapping
        mapping=self.cached("association",association_key,associate)
        feature_key = identity([sha,query["window_s"],task["ambient_pa"]])
        def compute():
            try:
                selected = window(rows,*query["window_s"])
            except ValueError:
                return {"status":"unknown","reason":"requested_window_not_covered"}
            return {"status":"available","values":metrics(selected,ambient_pa=task["ambient_pa"],pressure_unit="Pa")}
        extracted = self.cached("extraction",feature_key,compute)
        claims=[]
        for sensor_id in query["sensors"]:
            for observable in query["observables"]:
                item={"sensor":sensor_id,"observable":observable,"window_s":query["window_s"],"value":None}
                column=mapping.get(sensor_id)
                if observable not in SUPPORTED:
                    item.update(status="unknown",reason="observable_not_implemented")
                elif column is None or column >= len(rows[0])-1:
                    item.update(status="unknown",reason="nominal_probe_unresolved")
                elif extracted["status"]=="unknown":
                    item.update(status="unknown",reason=extracted["reason"])
                else:
                    item.update(status="available",value=extracted["values"][column][observable])
                claims.append(item)
        receipt={"source_sha256":sha,"native_coverage_s":[rows[0][0],rows[-1][0]],"nominal_column_map":mapping,
                 "actual_mesh_sampling_position_verified":False,"configuration_executed_this_run":False}
        delivery={"task_id":task["id"],"query_id":query["id"],"claims":claims,"receipt":receipt,
                  "physical_validity":"not_evaluated","complete_simulation_task":None,
                  "display_units":query.get("display_units","SI"),"machine_values":"always SI"}
        nodes={"configuration":plan_key,"collection":sha,"association":association_key,"extraction":feature_key,
               "delivery":identity([identity(query),feature_key,mapping])}
        if self.goal_state:
            delivery["goal_state"]={"task_digest":identity(task),"query_digest":identity(query),
                    "nodes":nodes,"changed_nodes":[k for k,v in nodes.items() if self.previous.get(k)!=v],
                    "dependencies":{"collection":["source"],"association":["configuration","collection"],"extraction":["collection","query.window","ambient"],"delivery":["association","extraction","query.outputs"]}}
            self.previous=nodes
        checks = oracle_check(source,task,query,delivery) if self.final_check else None
        if self.final_check:
            self.cost["checker_reads"]+=1
            self.cost["checker_bytes_read"]+=source.stat().st_size
        final_raw=source.read_bytes()
        self.cost["source_hash_reads"]+=1
        self.cost["source_bytes_read"]+=len(final_raw)
        if hashlib.sha256(final_raw).hexdigest()!=sha:
            raise ValueError("Source changed during replay; refusing delivery")
        destination=self.output_root/query["id"]
        destination.mkdir(exist_ok=False)
        for name,value in [("task.json",task),("query.json",query),("configuration.json",plan),("collection.json",receipt),("delivery.json",delivery),("check.json",checks)]:
            (destination/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (destination/"functions.fragment").write_text(plan["functions_fragment"],encoding="utf-8")
        self.cost["output_files"]+=7
        outcome={"claims":claims,"check":checks,"counts_this_query":dict(self.cost-before),
                 "elapsed_seconds":time.perf_counter()-started,"delivery_sha256":identity(delivery)}
        (destination/"run.json").write_text(json.dumps(outcome,indent=2),encoding="utf-8")
        self.cost["output_files"]+=1
        return outcome


def oracle_check(source, task, query, delivery):
    """Independent numerical implementation; no comparison against reference curves.

It rereads raw rows and integrates a piecewise-linear curve split at boundaries
and zero crossings. Unknown is correct abstention, not numerical success.
"""
    rows=read_scalar_probes(source)
    header=read_header(source)
    positions={s["id"]:s["position_m"] for s in task["sensors"]}
    start,end=query["window_s"]
    expected={}
    for sid in query["sensors"]:
        matches=[i for i,p in header.items() if sid in positions and math.dist(p,positions[sid])<1e-10]
        for obs in query["observables"]:
            key=(sid,obs)
            if obs not in SUPPORTED or len(matches)!=1 or rows[0][0]>start or rows[-1][0]<end:
                expected[key]=None;continue
            j=matches[0]+1;points=[];area=0.
            for a,b in zip(rows,rows[1:]):
                left,right=max(start,a[0]),min(end,b[0])
                if left>=right:continue
                def value(t):return a[j]+(b[j]-a[j])*(t-a[0])/(b[0]-a[0])-task["ambient_pa"]
                cuts=[left,right]
                x,y=value(left),value(right)
                if x*y<0:cuts.insert(1,left+(right-left)*(-x)/(y-x))
                for u,v in zip(cuts,cuts[1:]):area+=(max(0.,value(u))+max(0.,value(v)))*(v-u)/2
                points.extend([(left,x),(right,y)])
            peak=max(v for _,v in points)
            peak_time=min(t for t,v in points if math.isclose(v,peak,rel_tol=0,abs_tol=1e-10))
            expected[key]={"peak_overpressure_pa":peak,"sampled_peak_time_s":peak_time,"whole_window_positive_area_pa_s":area}[obs]
    mismatches=[]
    seen=set()
    for claim in delivery["claims"]:
        key=(claim["sensor"],claim["observable"])
        if key in seen or key not in expected:mismatches.append("duplicate_or_unrequested");continue
        seen.add(key);target=expected[key]
        if target is None:
            if claim["status"]!="unknown" or claim["value"] is not None:mismatches.append("unsupported_claim")
        elif claim["status"]!="available" or not math.isclose(claim["value"],target,rel_tol=1e-8,abs_tol=1e-7):
            mismatches.append("numeric_disagreement")
    if seen!=set(expected):mismatches.append("missing_claims")
    return {"mismatches":mismatches,"available_count":sum(v is not None for v in expected.values()),
            "unknown_count":sum(v is None for v in expected.values()),"physical_success":None}
