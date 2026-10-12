"""Single read-only query over stdin/stdout for the opt-in DSH context adapter."""
import contextlib,json,sys,os
from mcp_servers.principia_retrieval.task_navigation import prepare_task_navigation


def main():
    request=json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        from mcp_servers.principia_retrieval import knowledge_navigation as navigation
        if os.environ.get('PRINCIPIA_COMBINATION_GRAPH'):
            from experiments.retrieval_method.native_combination_server import locate
        else:
            from experiments.retrieval_method.native_factory_server import locate
        navigation.locate=locate
        packet=prepare_task_navigation(request['original_request'],navigation,request.get('budget',5000))
    print(json.dumps(packet,ensure_ascii=False,separators=(',',':')))


if __name__=='__main__':main()
