"""Same visible semantics and sources, materialized lookup at runtime."""
import os
from experiments.retrieval_method import native_lookup_server as projection
from experiments.retrieval_method.flat_lookup_semantics import FlatLookupSemantics


def main():
    projection.graph=lambda:FlatLookupSemantics(os.environ['PRINCIPIA_FLAT_LOOKUP'])
    projection.main()


if __name__=='__main__':main()
