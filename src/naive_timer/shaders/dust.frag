#version 430
// Soft round grain. The Gaussian falloff is what makes a few thousand
// overlapping sprites read as a continuous medium instead of confetti.

in vec2 vCorner;
in vec4 vColor;
out vec4 FragColor;

void main() {
    float r2 = dot(vCorner, vCorner);
    if (r2 > 1.0) discard;
    FragColor = vColor * exp(-4.0 * r2);
}
