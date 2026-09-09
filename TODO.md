# TODO

([x] done)

On shatter:
- [x] Nix the red fading effects
- [x] Can we do something with the scene lighting to cause the shattered shards
      to kind of sparkle intensely/noticeably? Alternatively, each shard could
      get a light source inside, with each one on a different rhythm of fading
      quickly to very high intensity and back down - we can iterate
  - The HDR chain is the enabler: a per-wedge specular pulse clipped to flat
    white in the old 8-bit pass, and now throws glare and streaks proportional
    to how hot it actually gets. light_intensity + flare are the levers, and
    there is no readout left to keep legible, so both can go well past their
    idle defaults.
  - Done as *transient point lights beside the pieces* rather than inside them:
    each is placed on a sphere around one wedge, in the hemisphere facing the
    camera (12-68 degrees off the view axis), and fades in and out over ~0.2 s.
    Being outside is what makes the flash land on the outward faces you can
    see; a light inside a closed solid only reaches the interior surfaces. Six
    `spark_*` sliders under Shatter, `spark_rate = 0` is the off switch. Notes
    and the measurements in docs/HANDOFF.md.
  - Still open, if it wants another pass: the glints do not yet key off the
    *sound* (no flash on the impact transient), and every spark is the light's
    own colour -- a little hue scatter might sell the dispersion.
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
		- [x] Whole-scene: 4x MSAA, re-requested on the offscreen HDR target
		      (the surface-format one no longer applies -- see docs/HANDOFF.md)
		- Not necessarily whole-scene; font?
	- Frosted effects
		- Instead of glow?
		- Also on shard itself?
	- [x] Exploration of raytracing/pass optimization (must it be raytracing?)
	      **No.** Glare and flare are screen-space post-passes over an HDR
	      buffer; nothing traces a ray. Whole chain is 0.84 ms at 420x620.
	- Refraction -- still open, and the one thing here that *would* want
	  something more than a post-pass
	- [x] Lens flare -- ghosts, halo and streaks in post_flare.frag. Gates
	      itself on light_intensity via the bright-pass threshold.
	- [x] Brightness/intensity slider, with the highlight whitening out of the
	      tonemap rather than a blend to #ffffff
	- More triangles (attempted, see feature branch - weird)
	- More shatter pieces (difficult!)
	- Configurable shatter gravity (attempted, bug)

- More movement
	- Camera
	- Y-axis rubber-banded wobble (configurable degrees, speed)

- Sound
	- Higher initial tone on shatter, for longer

