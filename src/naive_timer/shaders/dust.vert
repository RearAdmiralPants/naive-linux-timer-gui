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

// Eddies as lights. color.w = radiance (glow * envelope); 0 = dark.
const int MAX_EDDIES = 8;
uniform int uEddyCount;
uniform vec4 uEddyPos[MAX_EDDIES];
uniform vec4 uEddyColor[MAX_EDDIES];
uniform vec4 uEddyNova[MAX_EDDIES];  // shock radius, push, flash radiance, reach multiplier
uniform float uEddyReach;   // distance at which an eddy's light has fallen to half
uniform float uNovaHeat;    // emission of dust the shock front is passing through

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
    // smear; fade them out before they get there. Generous on purpose: a
    // grain 1.5 units from the eye is already a soft disc a tenth of the
    // frame wide, and a cloud's worth of those reads as bokeh, not dust.
    float nearFade = smoothstep(0.8, 2.5, eyeDist);
    float alpha = clamp(uOpacity * cl.shape.z * cl.extra.x * nearFade, 0.0, 1.0);

    vec3 scatter = cl.color.rgb * uLightColor * (uLightIntensity * phase * uBrightness);

    // Each eddy lights the dust around it, through the same phase function:
    // with forward-scattering dust, the grains between the eddy and the eye
    // blaze and the ones beyond it barely show -- which is what gives an
    // accretion torus a bright near side and a lit rim rather than a uniform
    // glowing donut.
    //
    // The falloff is the *square* of a 1/(1 + d^2/R^2) lobe, i.e. ~d^-4 far
    // out. Plain inverse-square is not local enough here: the phase function
    // peaks at ~28x for g = 0.75, so a d^-2 tail still lit grains clear across
    // the frame into a field of bokeh discs.
    vec3 heat = vec3(0.0);
    for (int e = 0; e < uEddyCount; ++e) {
        vec4 nova = uEddyNova[e];
        float glow = uEddyColor[e].w;
        // A supernova is the same light, much brighter and much further-
        // reaching, whitened -- the blast is hotter than the eddy ever was.
        float reach = uEddyReach * max(1.0, nova.w);
        vec3 tint = mix(uEddyColor[e].rgb, vec3(1.0), nova.z > 0.0 ? 0.6 : 0.0);
        glow += nova.z;
        if (glow <= 0.0) continue;
        vec3 fromEddy = pos - uEddyPos[e].xyz;
        float d2 = dot(fromEddy, fromEddy);
        float lobe = 1.0 / (1.0 + d2 / (reach * reach));
        float falloff = lobe * lobe;
        float cosE = dot(fromEddy * inversesqrt(max(d2, 1e-6)), toEye / eyeDist);
        scatter += cl.color.rgb * tint
                 * (glow * falloff * phaseHG(cl.shape.x, cosE) * uBrightness);
        if (nova.y > 0.0) {
            // Shock heating: dust inside the front glows on its own account,
            // independent of albedo -- this is emission, not reflection --
            // so even the darkest lane lights up as the shell crosses it.
            float s = (sqrt(d2) - nova.x) / (0.25 + 0.15 * nova.x);
            heat += mix(uEddyColor[e].rgb, vec3(1.0, 0.85, 0.6), 0.5)
                  * exp(-s * s) * nova.y * uNovaHeat / 9.0;
        }
    }
    vec3 radiance = albedo * (scatter + cl.color.rgb * uAmbient) + heat;
    vColor = vec4(radiance * alpha, alpha);
}
