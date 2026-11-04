# Spike C1: job system and worker isolation (B4, B21)

Throwaway code for the spike that ADR-0004 and ADR-0011 require before Phase 2.
It is not application code, it is never merged into `main`, and nothing here is
installed into the project. The findings are reported in
`docs/reports/spike-c1-job-system-and-isolation.md` on `main`.

Run it with `./run.sh`. It generates throwaway passwords into `.secrets/` (git
ignores it), renders the Redis ACL file, builds one worker image on Python
3.14, starts the services under the compose project `caipo-spike-c1`, runs the
probes, prints one line per requirement, and stops everything.
