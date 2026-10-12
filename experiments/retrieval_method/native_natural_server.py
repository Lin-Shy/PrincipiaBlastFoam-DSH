"""Experimental lexical concept expansion; never supply model names or values."""
import json
from mcp_servers.principia_retrieval import knowledge_navigation,server
from experiments.retrieval_method.native_draft_server import locate_drafts

# Linguistic equivalents only, not physical compatibility or model selection rules.
CONCEPTS=((('空气',),'air'),(('黏度','粘度'),'viscosity'),(('输运',),'transport'),(('温度',),'temperature'))


def hints(query):
    return [english for terms,english in CONCEPTS if any(term in query for term in terms)]


def locate(query,tutorial_case,translation='',budget=5000):
    extra=hints(query)
    if not extra:return locate_drafts(query,tutorial_case,translation,budget)
    note={'lexical_hints':extra,'scope':'Vocabulary expansion only; no model or coefficient values inferred.'}
    packet=locate_drafts(query,tutorial_case,translation+'\n'+' '.join(extra),budget)
    result={**packet,'query_expansion':note}
    if len(json.dumps(result,ensure_ascii=False,separators=(',',':')))<=budget:return result
    return packet


def main():
    knowledge_navigation.locate=locate
    server.main()


if __name__=='__main__':main()
