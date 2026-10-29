export const CHARACTERS = Object.freeze([
  { id: 'linux-builder', name: 'Linux Builder', inspiration: 'Linus Torvalds', note: 'Created Linux and Git' },
  { id: 'search-builder', name: 'Search Builder', inspiration: 'Larry Page', note: 'Co-created PageRank and Google Search' },
  { id: 'apple-inventor', name: 'Apple Inventor', inspiration: 'Steve Wozniak', note: 'Built the Apple I and Apple II' },
  { id: 'voxel-maker', name: 'Voxel Maker', inspiration: 'Markus Persson', note: 'Created Minecraft' },
  { id: 'ledger-architect', name: 'Ledger Architect', inspiration: 'Satoshi Nakamoto', note: 'Created Bitcoin; identity unknown' },
  { id: 'web-inventor', name: 'Web Inventor', inspiration: 'Tim Berners-Lee', note: 'Invented the World Wide Web' },
  { id: 'python-creator', name: 'Python Creator', inspiration: 'Guido van Rossum', note: 'Created Python' },
  { id: 'apollo-coder', name: 'Apollo Coder', inspiration: 'Margaret Hamilton', note: 'Led Apollo flight software' },
  { id: 'compiler-pioneer', name: 'Compiler Pioneer', inspiration: 'Grace Hopper', note: 'Pioneered compilers' },
  { id: 'c-creator', name: 'C Creator', inspiration: 'Dennis Ritchie', note: 'Created C and co-developed Unix' },
]);

export const DEFAULT_CHARACTER_ID = 'linux-builder';
export const CHARACTER_IDS = new Set(CHARACTERS.map((character) => character.id));
export const getCharacter = (id) => CHARACTERS.find((character) => character.id === id)
  ?? CHARACTERS[0];
