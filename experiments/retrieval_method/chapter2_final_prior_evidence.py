"""交付前核验已有阶段终态、冻结题集与证据文件，不重跑模型或历史测试。"""
import argparse
import hashlib
import json
from pathlib import Path


def sha(x):return hashlib.sha256(x.read_bytes()).hexdigest()
def load(x):return json.loads(x.read_text())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();p=args.archive
    phase=load(p/'audit/phase_a_manifest_001.json')
    for relative,expected in phase['artifacts'].items():
        if sha(p/relative)!=expected:raise ValueError('A阶段证据漂移:'+relative)
    dataset=p/'datasets/frozen_001';m=load(dataset/'manifest.json')
    for relative,expected in m['artifacts'].items():
        if sha(dataset/relative)!=expected:raise ValueError('题集漂移:'+relative)
    if (m['families'],m['questions'],m['development']['families'],m['test']['families'])!=(44,132,12,32):raise ValueError('划分不符')
    smoke=load(p/'audit/smoke_identity_001.json');replay=load(p/'audit/smoke_replay_001.json')
    if (smoke['planned']!=5 or len(smoke['results'])!=5 or smoke['request_response_identity_errors'] or
            smoke['response_models']!={'qwen3-8b':45} or replay['successful_replay']!=5 or replay['planned']!=5):raise ValueError('接入证据不符')
    historical=load(p/'audit/historical_replay_001/state.json')
    if (historical['state']!='finished' or historical['total']!=3600 or historical['completed_new']!=2570 or
            bool(historical['errors']) or bool(historical['changed_results'])):raise ValueError('历史重放未闭合')
    native=load(p/'audit/formal_all_native_replay_summary_001.json')
    if native['queries']!=2592 or native['passes']!=2592 or native['drifts']!=0 or native['online_llm_calls']!=0:raise ValueError('原生重放未闭合')
    answer=load(p/'audit/formal_postprocess_001/answers_001.json')
    if answer['answer_sessions']!=1728 or sum(answer['replay_counts'].values())!=2016 or answer['new_llm_calls']!=0:raise ValueError('回答/规划重放未闭合')
    integrity=load(p/'audit/formal_runtime_integrity_before_final_delivery_001.json')
    if integrity['status']!='verified':raise ValueError('冻结当前身份不符')
    files=['audit/phase_a_manifest_001.json','datasets/frozen_001/manifest.json','audit/historical_replay_001/state.json','audit/historical_replay_001/manifest.json','audit/dataset_freeze_check_001.json','audit/production_guard_001.json','audit/formal_freeze_gate_001.json','audit/formal_runtime_preflight_001.json','audit/formal_preseal_check_001.json','audit/formal_all_native_replay_summary_001.json','audit/formal_postprocess_001/answers_001.json','audit/formal_runtime_integrity_before_final_delivery_001.json','audit/final_authority_and_adapter_check_001.json']
    result={'schema':'pre-final-prior-stage-evidence-revalidation-v1','script_sha256':sha(Path(__file__)),'phase_a_artifact_hashes_verified':len(phase['artifacts']),'dataset_artifact_hashes_verified':len(m['artifacts']),'historical_replay_completed':3600,'historical_replay_errors':0,'formal_native_replay_passes':2592,'formal_answer_replay_sessions':1728,'formal_planner_replay_sessions':288,'frozen_runtime_current_integrity':'verified','new_model_calls':0,'evidence_sha256':{r:sha(p/r) for r in files},'remaining':'必要裁决、最终评分/费用/供应商审计、AI最终对照及论文交付未完成。','limits':'核验既有终态审计、阶段A和冻结题集文件身份，未重新执行历史或全原生重放。终态重放记录是过去真实执行的证据；源哈希核验不能替代语义真值。'}
    if args.output.exists():raise FileExistsError('需新的核验版本')
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('prior evidence revalidated; final QA/Office delivery still pending')


if __name__=='__main__':main()
