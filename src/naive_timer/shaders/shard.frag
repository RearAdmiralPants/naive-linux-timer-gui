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

out vec4 FragColor;

uniform sampler2D uText;   // numerals, coverage in .a (white, premultiplied)

uniform vec3 uLightPos;    // offscreen light, world space
uniform vec3 uCamPos;
uniform vec3 uGlassColor;
uniform vec3 uTextColor;

uniform float uSpecPower;     // tight highlight <- high .. low -> broad sheen
uniform float uSpecStrength;
uniform float uFresnel;       // rim brightness at grazing angles
uniform float uGlow;          // emissive numerals
uniform float uEtch;          // 0 = emissive/lit, 1 = etched into the glass
uniform float uBaseAlpha;

uniform float uAlarm;         // 0..1, pulses after the countdown hits zero

void main() {
    float cov = texture(uText, vUV).a;

    vec3 N = normalize(vNormal);

    // Etched numerals: bump the surface normal by the gradient of the glyph
    // coverage, so the engraving catches the light at its edges rather than
    // being painted on flat. dFdx/dFdy give us that gradient for free.
    if (uEtch > 0.0) {
        vec2 grad = vec2(dFdx(cov), dFdy(cov));
        N = normalize(N - uEtch * vec3(grad * 18.0, 0.0));
    }

    vec3 L = normalize(uLightPos - vWorld);
    vec3 V = normalize(uCamPos - vWorld);
    vec3 H = normalize(L + V);

    float diff = max(dot(N, L), 0.0);
    float spec = pow(max(dot(N, H), 0.0), uSpecPower) * uSpecStrength;
    float fres = pow(1.0 - max(dot(N, V), 0.0), 3.0) * uFresnel;

    vec3 col = uGlassColor * (0.12 + 0.40 * diff);
    col += vec3(spec) + vec3(fres) * uGlassColor;

    // Numerals. Emissive: they light up. Etched: they frost and scatter,
    // reading as absence rather than as light.
    vec3 emissive = uTextColor * cov * uGlow * (1.0 - uEtch);
    vec3 frosted = mix(col, uTextColor * 0.35 + vec3(0.28) * diff, cov * uEtch);
    col = mix(col + emissive, frosted, uEtch);

    float alpha = uBaseAlpha + spec + fres * 0.5 + cov * uGlow * (1.0 - uEtch);
    alpha = clamp(alpha + cov * uEtch * 0.25, 0.0, 1.0);

    // Alarm: fade toward a mostly-transparent dark red and back.
    const vec3 ALARM_COLOR = vec3(0.38, 0.02, 0.03);
    col = mix(col, ALARM_COLOR, uAlarm);
    alpha = mix(alpha, alpha * 0.40 + 0.08, uAlarm);

    FragColor = vec4(col, alpha);
}
