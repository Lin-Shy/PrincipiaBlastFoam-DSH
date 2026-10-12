"""Natural locator with explicit, source-checked case phase identity."""
from mcp_servers.principia_retrieval import knowledge_navigation,server
from experiments.retrieval_method.native_natural_server import locate as natural_locate
from experiments.retrieval_method.case_identity import phase_identity,attach_identity


def locate(query,tutorial_case,translation='',budget=5000):
    packet=natural_locate(query,tutorial_case,translation,budget)
    return attach_identity(packet,phase_identity(knowledge_navigation.navigator().engine,packet),budget)


def main():
    knowledge_navigation.locate=locate
    server.main()


if __name__=='__main__':main()
