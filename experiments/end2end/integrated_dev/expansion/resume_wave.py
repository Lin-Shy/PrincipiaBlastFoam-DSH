"""Resume only transport-interrupted arms after the stratified first-attempt queue."""
import sys
import argparse
from wave import ARMS,OUT,SOURCE,read,write

sys.path.insert(0,str(SOURCE.parent/"couette"))
from continue_interrupted import resume


def main(families):
    tag="family_wave" if families else "first_wave"
    selected=read(OUT/("intake_families.json" if families else "intake.json"))["selected"]
    resumed=[]
    errors=[]
    for task in selected:
        pair=OUT/task
        for arm in ARMS:
            root=pair/arm
            if not (root/"sealed.json").exists():
                errors.append([task,arm,"first attempt has no seal"])
                continue
            try:
                seal=read(root/"sealed.json")
                if (root/"continuation/sealed.json").exists() or not seal["unsettled"] or seal["requests"]>=100:
                    continue
                if read(pair/"manifest.json")["max_jobs"]:
                    resume(arm,pair,"node_exchange","field.json","field_sha256")
                else:
                    resume(arm,pair,exchange_name=None)
                resumed.append([task,arm])
                print(task,arm,"continuation sealed",flush=True)
            except (ValueError,OSError,RuntimeError) as exc:
                errors.append([task,arm,str(exc)])
    write(OUT/(tag+"_closeout.json"),dict(resumed=resumed,errors=errors))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--families",action="store_true")
    main(p.parse_args().families)
