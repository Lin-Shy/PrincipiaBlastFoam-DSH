"""Export only declared S12 task inputs, never reference scores or whole cases."""
import json

def prepare(target, workspace, pins, copy, write):
    root=workspace/'graduation-datasets/chapter03_simulation_tasks/benchmark/case_reviews/VanDorsselaer2018-TNT1kg/native_c_20261107/job-8941511/evidence'
    source=json.loads((root/'specification.json').read_text(encoding='utf-8'))
    import hashlib
    pins[str(root/'specification.json')]=hashlib.sha256((root/'specification.json').read_bytes()).hexdigest()
    # Positive allowlist: comparison/reference_rows never enter the task.
    specification={key:source[key] for key in ['source','source_phase','initial_air','mesh','model_scope']}
    write(target/'specification.json',specification)
    conditions={'id':'C3-S12-DEV-v1','identity':'fixed conditional instantaneous-products model; not an unpublished-condition reconstruction task',
        'end_time_s':.02205,'metric_window_s':[0,.022],'ambient_pa':101325,
        'probe_radii_m':[.25,.5,.75,1,1.5,2,2.5,3,3.5,4,4.5,5,5.5],
        'native_probe_mapping':'(0,r,0), probes, fixedLocations true, interpolationScheme cellPoint, every timestep',
        'control':{'deltaT':1e-8,'maxCo':.30,'maxDeltaT':1e-5,'writeInterval':.011,'writeControl':'adjustableRunTime'},
        'accuracy_status':'pending','resource_limits':'operator binding required; no implied grant'}
    write(target/'conditions.json',conditions)
    for rel in ['constant/phaseProperties','constant/dynamicMeshDict','system/fvSchemes','system/fvSolution']:
        copy(root/'case'/rel,target/'materials'/rel,pins)
    for rel in ['initialize_wedge_source.py','initialize_cartesian_products.py','foam_fields_snapshot.py']:
        copy(root/rel,target/'initialization'/rel,pins)
    (target/'request.md').write_text('''# S12 条件性1kg TNT自由场工程任务
用OpenFOAM9/blastFoam从空payload/case构建固定的瞬时JWL产物模型。
任务给出的specification.json是权威输入：完整球质量1kg，5度扇区质量1/72kg，
轴向x为[-5,5]m、径向中平面0..10m，1251×1250×1均匀wedge。
该模型不是原论文未公开爆轰过程的重建；不拟合参考峰值，不改变物理/网格来求通过。

共同提供四份固定字典和三个初始化脚本，两组均可复制，明确不评价重新发明初始化算法。
其余网格、初始/边界场、控制/采样、运行脚本、数据处理与交付由agent完成。
生成轴上退化wedge，front/back为wedge，其余外表面统一outlet；U初值零。
0/alpha.tnt初值严格为internalField uniform 0;，rho.air/rho.tnt为spec给定值，
T为EOS_consistent_T_K，p为101325Pa。除U/p外outlet为zeroGradient；
U为pressureInletOutletVelocity/value uniform (0 0 0)，p为pressureWaveTransmissive、
fieldInf 101325、lInf 1、value uniform 101325；front/back使用wedge。静态网格、laminar。

在获准计算节点blockMesh、checkMesh后，用postProcess生成初始0/C和0/V，
将三个初始化脚本及不含参考答案的specification.json复制到payload/init/，运行
python3 payload/init/initialize_wedge_source.py --package payload/init --case payload/case。
保持输入文本和64位scalar/32位label little-endian布局要求，保留source_initialization.json。
该初始化依赖当前原生网格的C/V，只允许指定布局；不使用笛卡尔质量公式替代wedge。
数值设置和13测点按conditions.json。控制writeFormat binary、writePrecision 12、
timePrecision 14、writeCompression off、runTimeModifiable false，保留初始及终态证据。
MPI进程数/分解由统一资源绑定决定，不能默认继承历史48进程授权。

提交payload/run_case.sh和case；交付完整日志、初始/终态回执、原始13点时程、
完整时间轴pressure.csv、metrics.json、压力图与绘图源码、report.md和复现说明。
在[0,.022]s计算超压峰值/最早峰时/全窗正超压面积，超压=p-101325Pa；缺窗不外推。
任何非有限/非正温度等异常照实记录，不能因End就授予完整成功或预测准确。
不读取原参考case、审核图、评分代码、reference_rows或其他运行结果。
''',encoding='utf-8')
