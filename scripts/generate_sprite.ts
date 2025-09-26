import { createClient } from "@supabase/supabase-js";
import sharp from "sharp";
import Spritesmith from "spritesmith";
import { promises as fs } from "fs";
import path from "path";
import os from "os";

const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SECRET_KEY!
);

async function generateSprite() {
  const bucket = "map-pins";
  const spriteBaseName = "map-sprite";
  const spriteName1x = `${spriteBaseName}.png`;
  const jsonName1x = `${spriteBaseName}.json`;
  const spriteName2x = `${spriteBaseName}@2x.png`;
  const jsonName2x = `${spriteBaseName}@2x.json`;

  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), "icons-"));

  // 1. List files
  const { data: files, error } = await supabase.storage.from(bucket).list();
  if (error) throw error;
  if (!files || files.length === 0) throw new Error("No icons found");

  const imageFiles = files.filter(
    (file) => file.name.endsWith(".png") && !file.name.startsWith(spriteBaseName)
  );

  const resizedPaths1x: string[] = [];
  const resizedPaths2x: string[] = [];

  // 2. Download and resize icons for both 1x and 2x scales
  console.log(`Found ${imageFiles.length} icons to process.`);
  for (const file of imageFiles) {
    const { data, error: downloadError } = await supabase.storage
      .from(bucket)
      .download(file.name);
    if (downloadError) throw downloadError;

    const inputBuffer = Buffer.from(await data.arrayBuffer());

    // Create 1x version (26x26)
    const resizedBuffer1x = await sharp(inputBuffer)
      .resize(26, 26, {
        fit: "contain",
        background: { r: 0, g: 0, b: 0, alpha: 0 },
      })
      .png()
      .toBuffer();
    const outPath1x = path.join(tmpDir, `1x-${file.name}`);
    await fs.writeFile(outPath1x, resizedBuffer1x);
    resizedPaths1x.push(outPath1x);

    // Create 2x version (52x52)
    const resizedBuffer2x = await sharp(inputBuffer)
      .resize(52, 52, {
        fit: "contain",
        background: { r: 0, g: 0, b: 0, alpha: 0 },
      })
      .png()
      .toBuffer();
    const outPath2x = path.join(tmpDir, `2x-${file.name}`);
    await fs.writeFile(outPath2x, resizedBuffer2x);
    resizedPaths2x.push(outPath2x);
  }

  // 3. Generate sprites and metadata using Spritesmith
  const runSpritesmith = (
    src: string[]
  ): Promise<Spritesmith.SpritesmithResult> =>
    new Promise((resolve, reject) => {
      Spritesmith.run({ src, algorithm: "binary-tree" }, (err, result) => {
        if (err) return reject(err);
        resolve(result);
      });
    });

  const [result1x, result2x] = await Promise.all([
    runSpritesmith(resizedPaths1x),
    runSpritesmith(resizedPaths2x),
  ]);

  // 4. Prepare and save sprite images and JSON files
  const generateJson = (
    coordinates: Spritesmith.SpritesmithResult["coordinates"],
    pixelRatio: number
  ) => {
    const spriteJson: Record<string, any> = {};
    for (const [file, coords] of Object.entries(coordinates)) {
      const name = path.basename(file, path.extname(file)).replace(/^(1x-|2x-)/, "");
      spriteJson[name] = { ...coords, pixelRatio };
    }
    return spriteJson;
  };

  const spriteJson1x = generateJson(result1x.coordinates, 1);
  const spriteJson2x = generateJson(result2x.coordinates, 2);

  const spritePath1x = path.join(tmpDir, spriteName1x);
  const jsonPath1x = path.join(tmpDir, jsonName1x);
  const spritePath2x = path.join(tmpDir, spriteName2x);
  const jsonPath2x = path.join(tmpDir, jsonName2x);

  await Promise.all([
    fs.writeFile(spritePath1x, result1x.image),
    fs.writeFile(jsonPath1x, JSON.stringify(spriteJson1x, null, 2)),
    fs.writeFile(spritePath2x, result2x.image),
    fs.writeFile(jsonPath2x, JSON.stringify(spriteJson2x, null, 2)),
  ]);

  // 5. Upload all four files to Supabase
  const uploadFile = (fileName: string, filePath: string, contentType: string) =>
    fs.readFile(filePath).then((buffer) =>
      supabase.storage.from(bucket).upload(fileName, buffer, {
        contentType,
        upsert: true,
      })
    );

  await Promise.all([
    uploadFile(spriteName1x, spritePath1x, "image/png"),
    uploadFile(jsonName1x, jsonPath1x, "application/json"),
    uploadFile(spriteName2x, spritePath2x, "image/png"),
    uploadFile(jsonName2x, jsonPath2x, "application/json"),
  ]);

  console.log(`✅ 1x and 2x sprites and JSON files uploaded.`);

  // 6. Clean up temporary directory
  await fs.rm(tmpDir, { recursive: true, force: true });
}

generateSprite().catch((err) => {
  console.error("Workflow failed:", err);
  process.exit(1);
});
