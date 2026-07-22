# TODO

- Optimizations
	- [x] Nebula baked into a 512^2 RG16F cubemap; stars stay procedural.
	      4K 30ms -> 6.5ms. See docs/HANDOFF.md.
	- Re-bake one cube face per frame to restore the nebula's drift?
	- default-params.json only auto-loads under NAIVE_TIMER_TUNE=1 -- intended?
	- Suggestions?

- Prettier
	- Front-complexity: begun, strange dashes on vertices; may wish to revisit entire strategy (sphere cross-section vs. smoothly-extruded-hexagon)
	- Antialiasing?
		- Not necessarily whole-scene; font?
	- Frosted effects
		- Instead of glow?
		- Also on shard itself?
	- Refraction (must it be raytracing?)
	- Lens flare?
	- More triangles
	- More shatter pieces
	- Configurable shatter gravity
	- Shatter fade to red -> Screenwide, not shard pieces

- Camera

- Sound
	- Higher initial tone on shatter, for longer

