#version 330 core

// EDIT ME. This file is hot-reloaded: save it and the running app picks it up
// on the next frame. A compile error is printed to the console and the last
// good program keeps rendering, so you cannot break the app from here.
//
// Every uniform below is driven by a live slider when the app is launched with
// NAIVE_TIMER_TUNE=1.

in vec3 vWorld;
in vec3 vNormal;
in vec2 vUV;
in float vCap;             // 1.0 on a wedge's radial cut faces

out vec4 FragColor;

uniform sampler2D uText;   // numerals, coverage in .a (white, premultiplied)
uniform float uShatterT;   // seconds since the break; 0 while intact

uniform vec3 uLightPos;    // offscreen light, world space
uniform vec3 uLightColor;
uniform float uLightIntensity;  // scalar radiance multiplier; 1.0 = as tuned
uniform vec3 uCamPos;
uniform vec3 uGlassColor;
uniform vec3 uTextColor;

uniform float uSpecPower;     // tight highlight <- high .. low -> broad sheen
uniform float uSpecStrength;
uniform float uFresnel;       // rim brightness at grazing angles
uniform float uGlow;          // emissive numerals
uniform float uEtch;          // 0 = emissive/lit, 1 = etched into the glass
uniform float uEtchDepth;     // how sharply the engraving tilts the normal
uniform float uBaseAlpha;

uniform sampler2D uNormalMap; // micro-detail terrain normals (tangent space)
uniform float uTerrainDetail; // 0 disables; strength of the grain tilt

// Value noise, copied from sky.frag so the two surfaces share one character.
float hash31(vec3 p) {
    p = fract(p * vec3(127.1, 311.7, 74.7));
    p += dot(p, p.zyx + 19.19);
    return fract((p.x + p.y) * p.z);
}

float noise3(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);          // smoothstep, kills lattice creases

    float n000 = hash31(i + vec3(0.0, 0.0, 0.0));
    float n100 = hash31(i + vec3(1.0, 0.0, 0.0));
    float n010 = hash31(i + vec3(0.0, 1.0, 0.0));
    float n110 = hash31(i + vec3(1.0, 1.0, 0.0));
    float n001 = hash31(i + vec3(0.0, 0.0, 1.0));
    float n101 = hash31(i + vec3(1.0, 0.0, 1.0));
    float n011 = hash31(i + vec3(0.0, 1.0, 1.0));
    float n111 = hash31(i + vec3(1.0, 1.0, 1.0));

    return mix(
        mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
        mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y),
        f.z
    );
}

float fbm3(vec3 p) {
    float sum = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 4; i++) {
        sum += amp * noise3(p);
        p *= 2.03;                         // not exactly 2: avoids axis banding
        amp *= 0.5;
    }
    return sum;
}

uniform float uAlarm;         // 0..1, pulses after the countdown hits zero

void main() {
    // The radial cut faces exist so the tumbling wedges are solid rather than
    // hollow shells. While the shard is whole they are interior surfaces
    // between neighbouring wedges: drawing them would double up translucent
    // layers and muddy the glass.
    if (vCap > 0.5 && uShatterT <= 0.0) {
        discard;
    }

    float cov = texture(uText, vUV).a;

    vec3 N = normalize(vNormal);

    // Etched numerals: bump the surface normal by the gradient of the glyph
    // coverage, so the engraving catches the light at its edges rather than
    // being painted on flat.
    //
    // The gradient is a *central difference in texture space*, not dFdx/dFdy.
    // Screen-space derivatives are evaluated once per 2x2 pixel quad, so on a
    // magnified glyph edge they are near-zero inside a quad and jump at its
    // boundary -- which is the stair-stepped, speckled engraving this replaces.
    //
    // The step is at least one texel (never sample inside a single texel and
    // read pure interpolation noise) and at least one pixel footprint (never
    // sample finer than the pixel actually covers, which would alias). fwidth
    // is still a screen-space derivative, but of vUV, which varies smoothly
    // across the face -- so it contributes no speckle of its own.
    if (uEtch > 0.0) {
        vec2 texel = 1.0 / vec2(textureSize(uText, 0));
        vec2 step = max(texel, fwidth(vUV));

        float left = texture(uText, vUV - vec2(step.x, 0.0)).a;
        float right = texture(uText, vUV + vec2(step.x, 0.0)).a;
        float down = texture(uText, vUV - vec2(0.0, step.y)).a;
        float up = texture(uText, vUV + vec2(0.0, step.y)).a;

        vec2 grad = vec2(right - left, up - down) * 0.5;
        N = normalize(N - uEtch * vec3(grad * uEtchDepth, 0.0));
    }

    // Micro-detail terrain: the macro displacement lives in the geometry, but
    // grain finer than a facet has to come from lighting. Sample the baked
    // normal map and tilt N by it. The map is tangent-space (z up), so the
    // tilt is applied in the surface's own frame -- build that frame from N
    // with an arbitrary-but-stable tangent, which is enough for a symmetric
    // grain whose only job is to break the glass up into ice.
    if (uTerrainDetail > 0.0) {
        vec3 mapN = texture(uNormalMap, vUV).rgb * 2.0 - 1.0;
        mapN.z = max(mapN.z, 0.1);          // never tilt past vertical
        vec3 T = normalize(cross(N, vec3(0.0, 0.0, 1.0)) + vec3(1e-4));
        vec3 B = cross(N, T);
        N = normalize(N + uTerrainDetail * (mapN.x * T + mapN.y * B - mapN.z * N) * 0.5);
    }

    vec3 L = normalize(uLightPos - vWorld);
    vec3 V = normalize(uCamPos - vWorld);
    vec3 H = normalize(L + V);

    float diff = max(dot(N, L), 0.0);
    float spec = pow(max(dot(N, H), 0.0), uSpecPower) * uSpecStrength;
    float fres = pow(1.0 - max(dot(N, V), 0.0), 3.0) * uFresnel;

    // The light tints what the light drives -- diffuse, specular, Fresnel --
    // but not the ambient floor, and not the emissive numerals below, which
    // glow on their own rather than reflecting anything.
    //
    // uLightIntensity is a plain radiance multiplier, not a blend toward white.
    // The whitening at high intensity is the *tonemap's* doing (see the
    // roll-off at the bottom): a per-channel curve saturates the strongest
    // channel first, so a hot core converges on white while the dim falloff
    // keeps the lamp's tint. Lerping uLightColor toward #ffffff would instead
    // bleach the penumbra too, which is not what a bright lamp does.
    vec3 lightE = uLightColor * uLightIntensity;
    vec3 col = uGlassColor * 0.12
             + uGlassColor * (0.40 * diff) * lightE;
    col += vec3(spec) * lightE + fres * uGlassColor * lightE;

    // Numerals. Emissive: they light up. Etched: they frost and scatter,
    // reading as absence rather than as light.
    vec3 emissive = uTextColor * cov * uGlow * (1.0 - uEtch);
    vec3 frosted = mix(col, uTextColor * 0.35 + vec3(0.28) * diff, cov * uEtch);
    col = mix(col + emissive, frosted, uEtch);

    // A highlight bright enough to blow out also has to *hide* what is behind
    // it -- stars showing through a blazing white bevel read as a compositing
    // bug, not as glass -- so the specular term carries the intensity into
    // alpha as well. It is clamped, so this only bites once the highlight is
    // genuinely hot.
    float alpha = uBaseAlpha + spec * uLightIntensity + fres * 0.5
                + cov * uGlow * (1.0 - uEtch);
    alpha = clamp(alpha + cov * uEtch * 0.25, 0.0, 1.0);

    // Alarm: fade toward a mostly-transparent dark red and back.
    //
    // Tint the *lit* surface rather than replacing it. Mixing straight to a
    // flat colour erased all shading at the pulse peak, so the tumbling
    // wedges became red silhouettes and the lighting on them -- which is
    // computed per-piece from their tumbled normals -- was invisible for half
    // of every pulse.
    const vec3 ALARM_COLOR = vec3(0.38, 0.02, 0.03);
    vec3 alarmLit = ALARM_COLOR * 0.55
                  + ALARM_COLOR * (1.7 * diff) * lightE
                  + vec3(spec) * 0.55 * lightE
                  + fres * ALARM_COLOR * 1.5;
    col = mix(col, alarmLit, uAlarm);
    alpha = mix(alpha, alpha * 0.40 + 0.08, uAlarm);

    // No tonemap here. This writes *linear radiance* into a floating-point
    // scene buffer, and post_composite.frag maps the whole frame -- shard, sky
    // and glare together -- exactly once, at the end.
    //
    // That relocation is what makes light_intensity worth having. While the
    // curve lived here, col was squashed into 0..1 before the sky behind it was
    // ever composited, so a highlight had nowhere to go: past radiance 2.22
    // every bevel pixel became the same flat white and the specular lost its
    // shape. Now the highlight keeps its true value all the way to the
    // bright-pass, which is what lets it throw glare proportional to how hot it
    // actually is.
    //
    // The alpha still matters and is still clamped: the glass blends over the
    // sky *in this buffer*, in linear radiance rather than in display space.
    FragColor = vec4(col, clamp(alpha, 0.0, 1.0));
}
