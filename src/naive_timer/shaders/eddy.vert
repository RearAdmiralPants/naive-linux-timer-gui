#version 430
// Eddy artwork: per eddy, one camera-facing core quad and two jet quads, all
// built from gl_VertexID (18 vertices per eddy, no buffers).
//
// A jet quad runs along the spin axis from the core outward and is widened
// perpendicular to both the axis and the view ray, so it is always seen
// broadside -- the cylindrical-billboard trick for beams and lightning.

const int MAX_EDDIES = 8;
uniform int uEddyCount;
uniform vec4 uEddyPos[MAX_EDDIES];    // w unused here
uniform vec4 uEddyAxis[MAX_EDDIES];   // xyz axis, w = orbit sign
uniform vec4 uEddyColor[MAX_EDDIES];  // rgb, w = glow (envelope already applied)
uniform mat4 uViewProj;
uniform vec3 uCamPos;
uniform vec3 uCamRight;
uniform vec3 uCamUp;
uniform float uCoreSize;
uniform float uJetLength;
uniform float uJetWidth;

out vec2 vUV;          // core: [-1,1]^2; jet: x across [-1,1], y along [0,1]
flat out int vKind;    // 0 core, 1 jet
flat out vec4 vColor;  // rgb, w = glow
flat out float vSeed;

const vec2 CORNERS[6] = vec2[](
    vec2(-1, -1), vec2(1, -1), vec2(1, 1),
    vec2(-1, -1), vec2(1, 1), vec2(-1, 1));

void main() {
    int e = gl_VertexID / 18;
    int part = (gl_VertexID % 18) / 6;
    vec2 c = CORNERS[gl_VertexID % 6];
    vColor = uEddyColor[min(e, MAX_EDDIES - 1)];
    vSeed = float(e) * 7.31;
    if (e >= uEddyCount || vColor.w <= 0.0) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        return;
    }

    vec3 center = uEddyPos[e].xyz;
    vec3 world;
    if (part == 0) {
        vKind = 0;
        vUV = c;
        world = center + (uCamRight * c.x + uCamUp * c.y) * uCoreSize;
    } else {
        vKind = 1;
        vec3 axis = normalize(uEddyAxis[e].xyz) * (part == 1 ? 1.0 : -1.0);
        vec3 toEye = normalize(uCamPos - center);
        vec3 across = cross(axis, toEye);
        float al = length(across);
        // Seen end-on the jet has no broadside; collapse it (the core covers it).
        across = al > 1e-3 ? across / al : uCamRight;
        float along = c.y * 0.5 + 0.5;
        vUV = vec2(c.x, along);
        // Flares open slightly with distance from the core.
        float width = uJetWidth * (0.35 + 0.9 * along);
        world = center + axis * (along * uJetLength) + across * (c.x * width);
    }
    gl_Position = uViewProj * vec4(world, 1.0);
}
