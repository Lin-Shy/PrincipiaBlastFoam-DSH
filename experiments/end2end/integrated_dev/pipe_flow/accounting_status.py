"""Read the persistent record for precisely one owned pipe job."""
import re
import cluster_job


def status(config,rid,receipt):
    job = receipt["job_id"]
    if not re.fullmatch(r"\d+",job) or receipt["run_id"] != rid:
        raise ValueError("invalid job identity")
    answer = cluster_job.ssh(config,"sacct -X -nP -j "+job+
        " -o JobID,JobName%64,State,ExitCode,Elapsed,AllocNodes,NodeList,WorkDir%250",capture_output=True,text=True)
    rows = [line.split("|") for line in answer.stdout.splitlines() if line.strip()]
    if len(rows)!=1 or len(rows[0])!=8:
        raise ValueError("missing or ambiguous accounting entry")
    job_id,name,state,exit_code,elapsed,nodes,host,workdir = rows[0]
    if (job_id,name,workdir)!=(job,rid,receipt["remote"]):
        raise ValueError("accounting entry does not match owned job")
    return dict(JobId=job,JobName=name,JobState=state,ExitCode=exit_code,RunTime=elapsed,
                NumNodes=nodes,NodeList=host,WorkDir=workdir)
