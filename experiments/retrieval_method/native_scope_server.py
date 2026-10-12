"""Experimental MCP ablation: same tools, but locator omits graph enrichment.

This is not the production server. Direct source reading and other tools remain
available; audit sessions for direct graph-CLI use before interpreting results.
"""
from mcp_servers.principia_retrieval import knowledge_navigation, server


def locate_scopes(query,tutorial_case,translation='',budget=5000):
    return knowledge_navigation.navigator().locate(
        query,tutorial_case,translation=translation,budget=budget,graph=False)


def main():
    knowledge_navigation.locate=locate_scopes
    server.main()


if __name__=='__main__':main()
