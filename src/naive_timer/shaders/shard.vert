#version 330 core

// Faceted glass shard. Each triangle is a flat-shaded facet, so the specular
// highlight breaks across the bevels instead of sliding smoothly over a dome.

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec2 aUV;
layout(location = 3) in vec3 aPieceDir;  // outward dir for the fracture

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;
uniform mat3 uNormalMat;

uniform float uFracture;  // 0 = intact, 1 = fully flown apart
uniform float uSpin;      // radians, slow idle rotation

out vec3 vWorld;
out vec3 vNormal;
out vec2 vUV;

void main() {
    // Facets drift outward along their own centroid direction. Keep this
    // small: the shard should read as cracked open, not as an explosion, and
    // the pieces must stay in frame so the numerals remain readable.
    vec3 pos = aPos;
    float f = uFracture;
    pos += aPieceDir * f * 0.07;
    pos.z -= f * f * 0.04;

    float c = cos(uSpin);
    float s = sin(uSpin);
    mat3 spin = mat3(c, 0.0, -s,
                     0.0, 1.0, 0.0,
                     s, 0.0, c);
    pos = spin * pos;

    vec4 world = uModel * vec4(pos, 1.0);
    vWorld = world.xyz;
    vNormal = normalize(uNormalMat * (spin * aNormal));
    vUV = aUV;

    gl_Position = uProj * uView * world;
}
