import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { basename, dirname, join } from 'node:path';

const require = createRequire(join(process.env.FISH_STICKER_KIT, 'package.json'));
const { StickerKit } = await import(pathToFileURL(require.resolve('dsh-nekowhale-stickers/core')));
const kit = new StickerKit({
    dataDir: process.env.FISH_STICKER_DATA,
    bundledMeta: join(dirname(require.resolve('dsh-nekowhale-stickers/package.json')), 'meta/nekowhale.json'),
});
const [action, ref, caption] = process.argv.slice(2);
let file;
if (action === 'meme') {
    file = 'renders/' + basename((await kit.render(ref, { text: caption })).path);
} else {
    const sticker = await kit.pick(ref) ?? (await kit.search(ref, { limit: 1 }))[0]?.sticker;
    if (!sticker) throw new Error('没有匹配的表情');
    await kit.file(sticker);
    file = 'byhash/' + sticker.hash + '.gif';
}
process.stdout.write(file);
process.exit(0);
