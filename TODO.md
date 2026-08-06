# TODO

([x] done)

On shatter:
- Nix the red fading effects
- Can we do something with the scene lighting to cause the shattered shards to kind of sparkle intensely/noticeably? Alternatively, each shard could get a light source inside, with each one on a different rhythm of fading quickly to very high intensity and back down - we can iterate
- Warm up the sound ~1s before shattering so e.g. bluetooth sinks don't miss the first 1/4s


---
- Optimizations
	- [x] Nebula baked into a 512^2 RG16F cubemap; stars stay procedural.
	      4K 30ms -> 6.5ms. See docs/HANDOFF.md.
	- Re-bake one cube face per frame to restore the nebula's drift?
	- default-params.json only auto-loads under NAIVE_TIMER_TUNE=1 -- intended? For now, esp with --json
	- Suggestions?

- Prettier
	- Front-complexity: begun, strange dashes on vertices; may wish to revisit entire strategy (sphere cross-section vs. smoothly-extruded-hexagon)
	- Antialiasing?
		- Not necessarily whole-scene; font?
	- Frosted effects
		- Instead of glow?
		- Also on shard itself?
	- Refraction and exploration of raytracing/pass optimization (must it be raytracing?)
	- Lens flare?
	- More triangles (attempted, see feature branch - weird)
	- More shatter pieces (difficult!)
	- Configurable shatter gravity (attempted, bug)

- More movement
	- Camera
	- Y-axis rubber-banded wobble (configurable degrees, speed)

- Sound
	- Higher initial tone on shatter, for longer

