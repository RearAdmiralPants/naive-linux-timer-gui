# gravitational-dust-eddies-albedo

New kind of feature branch testing a new workflow to see how it behaves given today's tooling.

This tiny utility was written partly by hand, partly with very task-isolated guidance by a human to the agent, and partly using propmts to refine the feature set of a branch before overseeing the implementation. There has never been a more comprehensive agentic approach, and the codebase is small and inconsequential enough to test one on an independent branch just to see what happens.

# Workflow

The idea is that based on a fairly high-level, vague goal:

Add drifting volumetric variable-volume clouds of dust drifting by at pseudorandom velocities and densitities. Randomly spawn a configurable number of gravitational eddies with some unrealistic graphics indicating their positions - relativistic jet artwork, for example, with a rotation animation? Use your discretion. When teh dust approaches these eddies, it's whipped about them at relativistic speeds, but some artistic license should be taken; not all of the dust which encounters such an eddie should be flung out of the scene at 0.999999999c. It would be much more visually interesting if it got caught in a visuall complicated, chaotic but organized orbit about the eddie until the eddie "lost gravitational pull" somehow (maybe it just dims in brightness), which "dislodges" the accumulated dust, allowing it to clump back together under its own gravitational influence and spread out into the erstwhile cloud again, or assume any transition state in between, before it presumably drifts offscreen or is influenced by another eddie and repeats the process.

Particularly cool would be when an eddit accumulates some critical mass of dust, it explodes in a Ia-style supernova, dispersing the dust in an impressive explosion, but redistributing the dust so that it can restart its journey.

Configurable variables: Dust cloud min. size, min. volume; max size, max volume; dust cloud color(s); eddie color(s); eddie visual effects; eddie gravitational pull/mass; how that mass is affected by pulling in dust clouds; etc. Other configurable variables at your discretion.

For this particular attempt on this particular branch, do not stop the workflow waiting on input from the human unless there is simply no possible way to proceed to any kind of pre-mvp or mvp/v0 release candidate without additional information. Try to gather any critically-needed information before beginning the workflow.

## Rules

The two primary goals are to make verifiable progress (finishing the feature or having a candidate is a bonus, but not a requirement) and not to significantly impact weekly usage, or to lock me out of my five-hour rolling subscription usage window. 

## Workflow parameters

Spawn additional models which you orchestrate to deliver the implementation. Don't go crazy; again, monitor usage. No more than four sub-agents underneath you, and none of them should be of your own capability (if you're Opus 5.5, restrict yourself to Sonnet-level agents, for example). Scale the subagent use appropriately based upon how it appears to be affecting usage. If you reach 33% of my total weekly usage (I have just under six days remaining in that window), execute a hard stop and wait for my input.

# Final remarks

This is an experiment in fully agentically-orchestrated development in a low-stakes codebase. Feel free to make mistakes. Worst case is we drop the feature branch and try it again, or (worse0 delete the local repo and re-clone it from remote. Relatively low danger in active harm to the repo in any meaningful way.

Other opinions or oversights I'm making are welcome. Please point them out.

# Decisions (agreed in session, 2026-11-12)

**Priorities.** Visual effects come before legibility. Dust may pass in front of the readout; digit glow/bloom is the lever for keeping it readable. Runs in every mode (stopwatch, timer, clock). The Eddies section of the tuning panel has a master on/off checkbox. Identifiers use `eddy`.

**Albedo.** Each cloud gets a random albedo (and scattering anisotropy) in a configurable range. Planned lighting, roughly in build order:
1. Henyey–Greenstein forward scattering of the scene light: backlit dust glows, side-lit dust stays dim.
2. Eddies as light sources: dust near an eddy is lit by its jets/disk, and goes dark as the eddy fades, before it scatters.
3. Shatter `spark_*` lights also light the dust.
4. Supernova: briefly the brightest light in the scene, feeding the HDR bloom/flare chain.
5. Stretch: dust seen through the shard's refraction; crepuscular rays.

**Rendering/sim.** Soft additive sprites in the HDR pass, not ray-marched volumes (the app is already fragment-bound). Cloud cohesion is faked with a centroid spring per cloud, not real N-body. The sim targets the GPU; OpenGL compute (4.3+) works on Intel/Mesa, NVIDIA and AMD alike, so no CUDA. numpy is the fallback. Target 30+ fps for v0 (60 fps is the standing goal, not a v0 gate); log performance hotspots for a later optimization pass.

**Budget.** `tools/usage_gate.py` checks this before each milestone and between agent tasks: pause when ahead of even five-hour pace by more than 30 min of projected lockout; hard stop at 33% weekly.

**Git.** Commit and push on this branch at my discretion. Merging to main requires the user's smoke test, a summary from me, and the user's signoff.

**Milestones.** M0 harness + gate · M1 drifting dust · M2 eddies + captured orbits · M3 fade, release, re-clump · M4 Ia supernova · M5 panel + presets. Post-MVP, high priority: shatter fragments caught by eddies.
