#version 430
// Dust sprites, built from the particle buffer with no vertex attributes:
// six vertices per particle, gl_VertexID / 6 picks the particle.
//
// Lighting is per particle (a sprite is far smaller than any lighting
// gradient), so all of it happens here and the fragment shader only shapes
// the falloff.
//
// Albedo is used in its physical sense: the fraction of the light a grain
// intercepts that it scatters rather than absorbs. Each sprite is blended
// premultiplied -- out = src.rgb + dst * (1 - src.a) -- so src.a is the light
// the grain *blocks* and src.rgb the light it *sends toward the eye*. A
// low-albedo cloud is therefore a dark lane that eats the stars behind it; a
// high-albedo one glows. Additive blending could only ever do the second.

struct Particle { vec4 pos; vec4 vel; };
struct Cloud { vec4 center; vec4 vel; vec4 color; vec4 shape; vec4 extra; };

layout(std430, binding = 0) readonly buffer Particles { Particle particles[]; };
layout(std430, binding = 1) readonly buffer Clouds { Cloud clouds[]; };

uniform mat4 uViewProj;
uniform vec3 uCamPos;
uniform vec3 uCamRight;
uniform vec3 uCamUp;
uniform vec3 uLightPos;
uniform vec3 uLightColor;
uniform float uLightIntensity;
uniform int uPerCloud;
uniform int uCloudCount;
uniform float uGrain;       // sprite half-size, scene units
uniform float uOpacity;     // per-sprite opacity before the cloud's own scale
uniform float uBrightness;  // multiplier on scattered light
uniform float uAmbient;     // faint omnidirectional fill, so unlit dust is not pure black

out vec2 vCorner;
out vec4 vColor;  // premultiplied: rgb already carries the alpha

const vec2 CORNERS[6] = vec2[](
    vec2(-1, -1), vec2(1, -1), vec2(1, 1),
    vec2(-1, -1), vec2(1, 1), vec2(-1, 1));

float hash(uint x) {
    x ^= x >> 16; x *= 0x7feb352du;
    x ^= x >> 15; x *= 0x846ca68bu;
    x ^= x >> 16;
    return float(x) / 4294967296.0;
}

// Henyey-Greenstein, normalised so an isotropic scatterer (g = 0) is 1.0
// rather than 1/(4 pi). g > 0 throws light forward (backlit dust blazes),
// g < 0 back toward the source (dust that reads as reflective).
float phaseHG(float g, float cosTheta) {
    float g2 = g * g;
    return (1.0 - g2) / pow(max(1.0 + g2 - 2.0 * g * cosTheta, 1e-4), 1.5);
}

void main() {
    int pid = gl_VertexID / 6;
    vec2 corner = CORNERS[gl_VertexID % 6];
    vCorner = corner;

    int ci = pid / uPerCloud;
    int local = pid - ci * uPerCloud;
    Cloud cl = clouds[min(ci, uCloudCount - 1)];
    Particle p = particles[pid];

    // Inactive slot, or a particle the step shader has not re-seeded yet:
    // park it outside the clip volume.
    if (ci >= uCloudCount || float(local) >= cl.shape.y * float(uPerCloud)
            || p.pos.w != cl.vel.w) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        vColor = vec4(0.0);
        return;
    }

    vec3 pos = p.pos.xyz;
    float size = uGrain * (0.45 + 1.1 * hash(uint(pid) * 2654435761u));
    vec3 world = pos + (uCamRight * corner.x + uCamUp * corner.y) * size;
    gl_Position = uViewProj * vec4(world, 1.0);

    vec3 toEye = uCamPos - pos;
    float eyeDist = length(toEye);
    float cosTheta = dot(normalize(pos - uLightPos), toEye / eyeDist);
    float phase = phaseHG(cl.shape.x, cosTheta);

    float albedo = cl.color.w;
    // Sprites that drift right up to the lens would cover the frame in one
    // smear; fade them out before they get there.
    float nearFade = smoothstep(0.25, 1.1, eyeDist);
    float alpha = clamp(uOpacity * cl.shape.z * cl.extra.x * nearFade, 0.0, 1.0);

    vec3 scatter = cl.color.rgb * uLightColor * (uLightIntensity * phase * uBrightness);
    vec3 radiance = albedo * (scatter + cl.color.rgb * uAmbient);
    vColor = vec4(radiance * alpha, alpha);
}
