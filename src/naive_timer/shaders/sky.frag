#version 330 core

// Procedural starfield and nebulae. No image asset: nothing to license, and it
// resamples cleanly at any window size.
//
// EDIT ME -- hot-reloaded on save, like shard.frag. A failed compile prints
// the error and keeps the last good program.

in vec2 vUV;
out vec4 FragColor;

uniform vec2 uResolution;
uniform float uTime;

uniform float uNebula;        // 0 = empty space, 1 = thick cloud
uniform vec3 uNebulaColorA;   // the cool lobe
uniform vec3 uNebulaColorB;   // the warm lobe
uniform float uStarDensity;   // cells per unit; more cells, more stars
uniform float uStarBrightness;

// The void is not pure black; a hint of blue reads as depth rather than as an
// unlit buffer.
const vec3 VOID_COLOR = vec3(0.020, 0.024, 0.038);

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

vec2 hash22(vec2 p) {
    float n = hash21(p);
    return vec2(n, hash21(p + n));
}

// Value noise: smooth interpolation between per-lattice-point randoms.
float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);          // smoothstep, kills lattice creases
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
    float sum = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 5; i++) {
        sum += amp * noise(p);
        p *= 2.03;                         // not exactly 2: avoids axis banding
        amp *= 0.5;
    }
    return sum;
}

// One layer of stars. The plane is diced into cells; each holds at most one
// star, placed and lit by the cell's hash. Bright stars are made rare by
// raising a uniform random to a high power.
float starLayer(vec2 p, float density, float radius, float seed) {
    vec2 grid = p * density + seed;
    vec2 cell = floor(grid);
    vec2 local = fract(grid);

    vec2 offset = hash22(cell) * 0.7 + 0.15;
    float brightness = pow(hash21(cell + 13.7), 7.0);

    float d = length(local - offset);
    float core = smoothstep(radius, 0.0, d);

    // Twinkle, desynchronised per star.
    float phase = hash21(cell + 3.1) * 6.2831853;
    float twinkle = 0.78 + 0.22 * sin(uTime * 1.7 + phase);

    return core * brightness * twinkle;
}

void main() {
    // Aspect-correct, so stars stay round and the nebula does not stretch when
    // the window is resized.
    float aspect = uResolution.x / max(uResolution.y, 1.0);
    vec2 p = (vUV - 0.5) * vec2(aspect, 1.0);

    vec3 color = VOID_COLOR;

    // Nebula. A second fbm displaces the first (domain warping), which is what
    // turns round blobs into filaments and wisps.
    vec2 drift = vec2(uTime * 0.006, uTime * 0.0025);
    float base = fbm(p * 2.3 + drift);
    float warped = fbm(p * 3.1 + base * 1.6 - drift);

    // A wide, low threshold. Clamping hard at the top left one faint smudge in
    // a corner instead of cloud across the frame.
    float density = smoothstep(0.28, 0.78, warped) * uNebula;
    vec3 cloud = mix(uNebulaColorA, uNebulaColorB, smoothstep(0.25, 0.75, base));
    color += cloud * density;

    // Three star layers at different scales read as depth.
    float stars = 0.0;
    stars += starLayer(p, uStarDensity * 0.6, 0.055, 0.0) * 1.00;
    stars += starLayer(p, uStarDensity * 1.3, 0.040, 17.0) * 0.65;
    stars += starLayer(p, uStarDensity * 2.4, 0.030, 41.0) * 0.40;
    color += vec3(stars) * uStarBrightness;

    // The nebula sits in front of the faintest stars, as dust does.
    color = mix(color, color * 0.75 + cloud * density * 0.4, density * 0.5);

    FragColor = vec4(color, 1.0);
}
