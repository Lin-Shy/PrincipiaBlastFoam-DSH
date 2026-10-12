"""Read-only task binding for an optional pre-model navigation stage."""
from mcp_servers.principia_retrieval.file_navigation import explicit_case_matches
from mcp_servers.principia_retrieval.request_context import locate_with_context


def prepare_task_navigation(original_request,navigation,budget=5000):
    if not isinstance(original_request,str) or not original_request.strip() or len(original_request)>32768:
        raise ValueError('invalid original request')
    engine=navigation.navigator().engine
    matches=explicit_case_matches(original_request,engine.graph['cases'],engine.graph.get('aliases',{}))
    if len(matches)!=1:return {'status':'not_applicable','reason':'no_unique_explicit_case'}
    case=next(iter(matches))
    return locate_with_context(navigation.locate,original_request,case,'',budget,original_request)
