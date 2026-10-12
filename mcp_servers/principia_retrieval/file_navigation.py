"""Optional task navigation alongside an unchanged tutorial file inventory."""
import re
from mcp_servers.principia_retrieval.request_context import locate_with_context


def explicit_case_matches(text,cases,aliases):
    found=set()
    for name in set(cases)|set(aliases):
        short=name.removeprefix('tutorials/')
        if re.search(r'(?<![A-Za-z0-9_/-])(?:tutorials/)?'+re.escape(short)+r'(?![A-Za-z0-9_/-])',text):
            found.add(aliases.get(name,name).removeprefix('tutorials/'))
    return found


def attach_file_navigation(inventory,original_request,navigation):
    if not original_request or not inventory.get('found'):return inventory
    try:
        engine=navigation.navigator().engine
        matches=explicit_case_matches(original_request,engine.graph['cases'],engine.graph.get('aliases',{}))
        case=inventory['case_path'].removeprefix('tutorials/')
        if matches!={case}:return inventory
        packet=locate_with_context(navigation.locate,original_request,case,'',5000,original_request)
    except (ValueError,OSError) as error:
        packet={'status':'navigation_unavailable','error_type':type(error).__name__}
    # Navigation may propose edits for review; this function never applies any.
    # No inventory field or file entry is filtered, rewritten, or truncated.
    return {'task_navigation':packet,**inventory}
