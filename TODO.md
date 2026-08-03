# TODO

- Bugs
	- [x] **Random segfault after ~45 minutes.** Root-caused 3Aug from five saved
	      core dumps: Qt 6.11's native **PipeWire audio backend** crashes the
	      process whenever the audio sink it is attached to disappears. Nothing
	      to do with the GL code, the lock screen, or elapsed time -- 45 minutes
	      was just how long it took for something in the session to change the
	      audio device list. Fixed by pinning `QT_AUDIO_BACKEND=PulseAudio` in
	      `app.py`. See docs/HANDOFF.md for the diagnosis and the reproducer.


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
	- Shatter fade to red -> Screenwide, not shard pieces (un-deprecate)

- More movement
	- Camera
	- Y-axis rubber-banded wobble (configurable degrees, speed)

- Sound
	- Higher initial tone on shatter, for longer

