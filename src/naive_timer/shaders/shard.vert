#version 330 core

// Faceted glass shard. Each triangle is a flat-shaded facet, so the specular
// highlight breaks across the bevels instead of sliding smoothly over a dome.
//
// On shatter, each wedge becomes an independent rigid body: it spins about its
// own centroid and translates away under its own velocity, rather than being
// pushed radially outward from the shard's centre (which read as a pinwheel).

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec2 aUV;

// Per-wedge rigid-body state. Every vertex of a wedge carries identical
// values, so the whole solid chunk moves together.
layout(location = 3) in vec3 aPieceCenter;  // pivot: the wedge's centroid
layout(location = 4) in vec3 aPieceVel;     // linear velocity, units/sec
layout(location = 5) in vec3 aPieceAxis;    // rotation axis; |axis| = rad/sec

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;
uniform mat3 uNormalMat;

uniform float uShatterT;  // seconds since the break; 0 while intact
uniform float uSpin;      // radians, slow idle rotation

out vec3 vWorld;
out vec3 vNormal;
out vec2 vUV;

// Gravity, so the pieces fall away rather than drifting flat.
const vec3 GRAVITY = vec3(0.0, -0.32, 0.0);

mat3 axisRotation(vec3 axis, float angle) {
    float c = cos(angle);
    float s = sin(angle);
    float t = 1.0 - c;
    vec3 a = normalize(axis);
    return mat3(
        t * a.x * a.x + c,       t * a.x * a.y + s * a.z, t * a.x * a.z - s * a.y,
        t * a.x * a.y - s * a.z, t * a.y * a.y + c,       t * a.y * a.z + s * a.x,
        t * a.x * a.z + s * a.y, t * a.y * a.z - s * a.x, t * a.z * a.z + c
    );
}

mat3 spinY(float angle) {
    float c = cos(angle);
    float s = sin(angle);
    return mat3(c, 0.0, -s,
                0.0, 1.0, 0.0,
                s, 0.0, c);
}

void main() {
    vec3 pos = aPos;
    vec3 nrm = aNormal;

    if (uShatterT > 0.0) {
        float t = uShatterT;
        float rate = length(aPieceAxis);
        mat3 tumble = rate > 1e-5
            ? axisRotation(aPieceAxis, rate * t)
            : mat3(1.0);

        // Rotate about the wedge's own centroid, then carry it away.
        pos = aPieceCenter + tumble * (aPos - aPieceCenter);
        pos += aPieceVel * t + 0.5 * GRAVITY * t * t;
        nrm = tumble * aNormal;
    } else {
        // Idle: the whole shard turns slowly on its axis, showing its edge.
        mat3 spin = spinY(uSpin);
        pos = spin * pos;
        nrm = spin * nrm;
    }

    vec4 world = uModel * vec4(pos, 1.0);
    vWorld = world.xyz;
    vNormal = normalize(uNormalMat * nrm);
    vUV = aUV;

    gl_Position = uProj * uView * world;
}
