#version 430
// Eddy core and jets, emitted straight into the HDR buffer (additive). The
// values are deliberately far above 1: the bright-pass, glare and flare do
// the rest, which is most of why this reads as something hot.

in vec2 vUV;
flat in int vKind;
flat in vec4 vColor;
flat in float vSeed;
flat in vec3 vNova;
out vec4 FragColor;

uniform float uTime;
uniform float uJetSpeed;   // how fast the knots travel outward

void main() {
    float glow = vColor.w;
    vec3 tint = vColor.rgb;
    if (vKind == 0) {
        // A white-hot point inside a coloured halo, with a thin photon ring
        // that breathes. The core is whiter than the halo because a hot body's
        // centre saturates first.
        // NB: never pow() a possibly-negative base -- GLSL leaves it undefined,
        // drivers return NaN, and one NaN pixel is smeared into a black block
        // by the bloom blur. Square by multiplying.
        float r = length(vUV);
        if (r > 1.0) discard;
        if (vNova.y > 0.0 || vNova.z > 0.0) {
            // Supernova: a blinding white flash at the centre and a thin,
            // hot, slightly ragged shell racing outward. Ragged because a
            // perfect circle reads as a UI element, not an explosion.
            float flash = exp(-r * r * 9.0) * vNova.y * 0.12;
            float ang = atan(vUV.y, vUV.x);
            float rag = 0.03 * sin(ang * 7.0 + vSeed) + 0.02 * sin(ang * 13.0 - vSeed * 2.0);
            float d = (r - vNova.x - rag) * 22.0;
            float shell = exp(-d * d) * vNova.z * 0.6;
            vec3 hot = vec3(1.0, 0.92, 0.8);
            vec3 col = hot * flash + mix(vColor.rgb, hot, 0.5) * shell;
            FragColor = vec4(max(col, 0.0), 0.0);
            return;
        }
        float core = exp(-r * r * 220.0) * 10.0;
        float halo = exp(-r * r * 18.0) * 0.25;
        float ringD = (r - 0.30 - 0.02 * sin(uTime * 3.0 + vSeed)) * 30.0;
        float ring = exp(-ringD * ringD) * 0.35;
        vec3 col = mix(tint, vec3(1.0), 0.65) * core + tint * (halo + ring);
        FragColor = vec4(max(col * glow, 0.0), 0.0);
        return;
    }

    // Jet: a tight bright spine, a soft sheath, knots travelling outward and a
    // helical twist (the spine wanders side to side as a sine of distance and
    // time), all fading with distance.
    float along = clamp(vUV.y, 0.0, 1.0);  // interpolation can overshoot 1 by an ulp
    float twist = 0.28 * sin(along * 14.0 - uTime * 2.3 * uJetSpeed + vSeed) * along;
    float x = vUV.x - twist;
    float spine = exp(-x * x * 90.0);
    float sheath = exp(-x * x * 6.0) * 0.35;
    float knots = 0.55 + 0.45 * pow(0.5 + 0.5 * sin(along * 26.0 - uTime * 6.0 * uJetSpeed + vSeed * 3.0), 6.0);
    float fade = pow(1.0 - along, 1.6) * smoothstep(0.0, 0.06, along);
    float edge = 1.0 - smoothstep(0.75, 1.0, abs(vUV.x));
    vec3 col = (mix(tint, vec3(1.0), 0.25) * spine * 2.5 + tint * sheath * 1.6) * knots;
    FragColor = vec4(max(col * fade * edge * glow, 0.0), 0.0);
}
