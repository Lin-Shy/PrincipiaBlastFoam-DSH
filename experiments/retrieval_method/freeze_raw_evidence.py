"""Expose the same frozen raw facts to every retrieval-policy arm."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def main():
    p=argparse.ArgumentParser();p.add_argument('--factory-graph',type=Path,required=True)
    p.add_argument('--combination-build',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);manifest={}
    def copy(source,relative,expected=None):
        raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        if expected is not None and expected!=sha:raise ValueError('raw evidence source changed')
        target=out/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        manifest[relative]=sha
    graph=json.loads(a.factory_graph.read_text());factory_root=a.factory_graph.resolve().parent
    for rel,sha in graph['inventory'].items():
        source=(factory_root/rel).resolve()
        if not source.is_relative_to(factory_root):raise ValueError('factory source escapes archive')
        copy(source,'blastfoam/'+rel,sha)
    combination=a.combination_build.resolve();inventory=json.loads((combination/'inventory.json').read_text())
    identity=json.loads((combination/'identity.json').read_text())
    for rel,sha in inventory.items():
        source=(combination/rel).resolve()
        if not source.is_relative_to(combination):raise ValueError('compiler source escapes archive')
        copy(source,'compiler/'+rel,sha)
    copy(combination/'expanded.cpp','compiler/expanded.cpp',identity['expanded_sha256'])
    copy(combination/'dependencies.make','compiler/dependencies.make')
    (out/'raw-manifest.json').write_text(json.dumps(manifest,indent=2))
    (out/'README.md').write_text('# 三组共同原始证据\n\nblastfoam/ 是工厂路径所引用的原始源码；compiler/sources/ 是编译单元的完整源码依赖；compiler/expanded.cpp 是同一编译单元的编译器展开文本。全部组可用普通文本搜索/读取这些文件。这里不包含图节点、边、评测目标、正确答案、运行结果或修改草案。编译展开只证明源码声明，不证明当前二进制构建/加载或物理正确。\n')
    print(json.dumps({'raw_files':len(manifest),'output':str(out)}))


if __name__=='__main__':main()
