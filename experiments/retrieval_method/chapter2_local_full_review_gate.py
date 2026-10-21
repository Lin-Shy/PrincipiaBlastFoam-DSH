"""Reconstruct frozen worker arguments from the registered controller command."""
from pathlib import Path
from types import SimpleNamespace


def source_release_args(proof):
    command=proof['prepared_launch_base_command']
    opts={command[i][2:].replace('-','_'):command[i+1] for i in range(2,len(command),2)}
    args=SimpleNamespace(**{k:(v if k=='stage' else Path(v)) for k,v in opts.items()})
    # The controller's output is a billing run; worker output is score_output.
    # Keep the original score root for verifying historic source opinions, even
    # though subsequent local scores have a separate destination.
    args.output=args.score_output
    return args
