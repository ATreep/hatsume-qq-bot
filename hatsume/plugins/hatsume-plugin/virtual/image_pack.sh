docker build --no-cache -t hatsume-space-kali:1.0 ./image
docker save hatsume-space-kali:1.0 | zstd -T0 -19 > hatsume-space-kali-image.tar.zst