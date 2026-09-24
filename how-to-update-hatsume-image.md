# How to Update hastume-space Image and Re-create hatsume-containerization
1. Update `hatsume/hatsume/plugins/hatsume-plugins/virtual/image_pack.sh` and `hatsume/hatsume/plugins/hatsume-plugins/virtual/image/Dockerfile`,
2. Pack new image by running `image_pack.sh`.
3. Re-create container by running `hatsume-containerization/start_hatsume_container.sh`
