/**
 * Runtime version validation for Node.js.
 * This script checks Node.js version compatibility and exits with error code 1 if incompatible.
 */

// Minimum required Node.js version
const REQUIRED_NODE_MAJOR = 18;
const REQUIRED_NODE_MINOR = 17;

function getNodeVersion() {
  const version = process.version;
  // Remove 'v' prefix and split into parts
  const parts = version.slice(1).split('.').map(Number);
  return {
    major: parts[0],
    minor: parts[1],
    patch: parts[2] || 0,
    full: version,
  };
}

function checkNodeVersion() {
  const current = getNodeVersion();
  
  // Log detected version
  console.log(`[VERSION CHECK] Detected Node.js ${current.full}`);
  
  // Check major version
  if (current.major < REQUIRED_NODE_MAJOR) {
    const errorMsg = [
      `❌ Incompatible Node.js version detected: ${current.full}`,
      `   Required: Node.js ${REQUIRED_NODE_MAJOR}.${REQUIRED_NODE_MINOR}.0+ (Node.js 18.17 or higher)`,
      `   Detected: Node.js ${current.full}`,
      `   Please upgrade Node.js to a compatible version.`,
    ].join('\n');
    console.error(errorMsg);
    process.exit(1);
  }
  
  // Check minor version if major matches
  if (current.major === REQUIRED_NODE_MAJOR && current.minor < REQUIRED_NODE_MINOR) {
    const errorMsg = [
      `❌ Incompatible Node.js version detected: ${current.full}`,
      `   Required: Node.js ${REQUIRED_NODE_MAJOR}.${REQUIRED_NODE_MINOR}.0+ (Node.js 18.17 or higher)`,
      `   Detected: Node.js ${current.full}`,
      `   Please upgrade Node.js to a compatible version.`,
    ].join('\n');
    console.error(errorMsg);
    process.exit(1);
  }
  
  // Success
  console.log(
    `[VERSION CHECK] ✓ Node.js version ${current.full} is compatible (requires ${REQUIRED_NODE_MAJOR}.${REQUIRED_NODE_MINOR}.0+)`
  );
}

// Run check
checkNodeVersion();

