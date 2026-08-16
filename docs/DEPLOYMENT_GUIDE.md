# DMI Deployment Guide

**Version**: 0.1.10  
**Purpose**: Platform-agnostic deployment instructions for any web host

---

## Overview

The DMI dashboard is a **static web application** requiring only:
- Web server with HTML/CSS/JavaScript support
- No server-side code (PHP, Python, Node.js)
- No database
- No special modules or dependencies

This makes it compatible with virtually any web hosting provider.

---

## Universal Deployment Steps

### Step 1: Prepare Deployment Package

On your local machine:

```bash
cd /path/to/dmi
./prepare_deployment.sh
```

This creates:
- `deploy/` directory with all files
- `dmi-v0.1.10-deployment.zip` (compressed archive)

### Step 2: Upload Files

Choose the method that works for your host:

#### Method A: FTP/SFTP Upload

1. **Connect to your host**:
   - Use FTP client (FileZilla, Cyberduck, Transmit, etc.)
   - Host: Provided by your hosting provider
   - Username: Your hosting username  
   - Password: Your hosting password
   - Port: 21 (FTP) or 22 (SFTP)

2. **Navigate to web root** (see Platform Guide below)

3. **Upload files**:
   - Drag entire contents of `deploy/` folder
   - OR upload to subdirectory (e.g., `/public_html/dashboard/`)
   - Verify all files uploaded successfully

#### Method B: Control Panel File Manager

1. **Log into hosting control panel** (cPanel, Plesk, DirectAdmin, etc.)

2. **Open File Manager**

3. **Navigate to web root directory**

4. **Option 1 - Upload directory**:
   - Upload all files from `deploy/` folder individually
   
5. **Option 2 - Upload .zip**:
   - Upload `dmi-v0.1.10-deployment.zip`
   - Right-click → Extract
   - Delete .zip fil after extraction

### Step 3: Verify File Permissions

Most hosts set these automatically, but verify:

- **Files**: `644` (rw-r--r--)
- **Directories**: `755` (rwxr-xr-x)

To check/fix:
- **cPanel**: Select files → Permissions → Set to 644/755
- **FTP Client**: Right-click → File Permissions
- **SSH**: `chmod 644 deploy/*.* && chm

od 755 deploy/*/`

### Step 4: Test Deployment

Visit your dashboard URL and verify:

- [ ] Dashboard loads (no blank page)
- [ ] Time series chart renders
- [ ] Health endpoint returns 200: `https://yourdomain.com/path/health.json`
- [ ] Latest period matches expected
- [ ] No console errors (F12 → Console tab)
- [ ] Data files accessible (test one .json URL)
- [ ] Mobile responsive (test on phone)

---

## Platform-Specific Guide

### cPanel Hosts
**Providers**: HostGator, Bluehost, SiteGround, Hostinger, GoDaddy, etc.

**Web Root**: `public_html/` or `public_html/yourdomain.com/`

**Upload Options**:
1. **File Manager** (built into cPanel) - Easiest
2. **FTP** - Use FileZilla or similar

**For Subdirectory** (e.g., `yourdomain.com/dashboard/`):
- Upload to: `public_html/dashboard/`
- Access at: `https://yourdomain.com/dashboard/`

**For Subdomain** (e.g., `data.yourdomain.com`):
1. Create subdomain in cPanel: Domains → Subdomains
2. Upload to the subdomain's directory (e.g., `public_html/data/`)
3. Access at: `https://data.yourdomain.com/`

**.htaccess**: Fully supported, no changes needed

---

### Plesk Hosts

**Web Root**: `httpdocs/` or `httpsdocs/` (SSL)

**Upload**: File Manager or FTP

**Subdomain Setup**:
1. Websites & Domains → Add Subdomain
2. Upload files to subdomain directory
3. **.htaccess** fully supported

---

### DirectAdmin Hosts

**Web Root**: `public_html/` or `domains/yourdomain.com/public_html/`

**Upload**: File Manager or FTP

**.htaccess**: Fully supported

---

### Nginx Hosts (VPS/Cloud)

**Web Root**: Varies (often `/var/www/html/`, check your config)

**Important**: **.htaccess NOT supported** (Nginx ignores Apache .htaccess files)

**Dashboard still works**, but you'll miss caching/compression optimizations.

**Optional**: Add equivalent config to your Nginx server block:

```nginx
location /dashboard/ {
    # Browser caching
    expires 1h;
    add_header Cache-Control "public, must-revalidate";
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-XSS-Protection "1; mode=block";
    add_header X-Content-Type-Options "nosniff";
    
    # CORS for JSON files (if needed)
    location ~ \.json$ {
        add_header Access-Control-Allow-Origin "*";
    }
}
```

Reload Nginx: `sudo nginx -s reload`

---

### Custom Apache VPS

**Web Root**: Check Apache config (`DocumentRoot` directive in `/etc/apache2/sites-enabled/`)

**.htaccess**: Ensure `AllowOverride All` is set:

```apache
<Directory /var/www/html>
    AllowOverride All
</Directory>
```

**Upload**: SFTP, rsync, or `git pull`

Restart Apache if needed: `sudo systemctl restart apache2`

---

### Shared Hosting (No Control Panel)

**Web Root**: Contact support or check documentation
- Common: `www/`, `html/`, `htdocs/`, `public/`

**Upload**: FTP/SFTP only (no file manager)

**Check**: Whether `.htaccess` is supported (ask support)

---

## Smoke Test Checklist

After deployment, systematically verify:

### Basic Functionality
- [ ] **Dashboard loads**: Visit `https://yourdomain.com/path/`
- [ ] **No 404 errors**: Check browser Network tab (F12)
- [ ] **index.html displays**: Page title shows "Distributional Misery Index"

### Data Loading
- [ ] **Health endpoint**: `https://yourdomain.com/path/health.json` returns JSON
- [ ] **Latest period matches**: Check health.json shows correct period
- [ ] **Time series accessible**: Test `/data/outputs/published/dmi_timeseries_2010_2024.json`

### Visualizations
- [ ] **Bar charts render**: DMI and inflation bars visible
- [ ] **Time series chart**: 2011-2024 line chart displays
- [ ] **Historical context**: Percentile, vs average, trend show values
- [ ] **No JavaScript errors**: Console tab clean

### Cross-Device
- [ ] **Desktop**: Full layout displays correctly
- [ ] **Mobile**: Responsive design works (charts resize)
- [ ] **Tablet**: Intermediate size renders well

---

## Common Issues & Solutions

| Issue | Symptoms | Solution |
|-------|----------|----------|
| **404 errors** | "Not Found" for .json files | Verify upload completed, check file paths match |
| **Blank page** | Dashboard doesn't load | Check browser console for errors, verify index.html uploaded |
| **Old data** | health.json shows old period | Clear browser cache (Ctrl+F5), verify new files uploaded |
| **Charts missing** | Bar charts work, time series doesn't | Verify Chart.js CDN accessible (check Network tab) |
| **Permission errors** | 403 Forbidden | Set files to 644, directories to 755 |
| **Broken layout** | CSS not loading | Check .css file uploaded, clear cache |

### Debugging Steps

1. **Open browser console** (F12 → Console)
2. **Look for red errors**
3. **Check Network tab** for failed requests
4. **Verify file paths** match your upload location
5. **Test health.json first** - if this fails, paths are wrong

---

## Rollback Procedure

### Before Each Update

**Backup current version**:

```bash
# Via SSH/SFTP
mv public_html/dashboard public_html/dashboard-backup-2024-12-17

# Or via File Manager
# Right-click dashboard → Rename to dashboard-backup-2024-12-17
```

### If Issues Occur

**Option 1 - SSH**:
```bash
rm -rf public_html/dashboard
mv public_html/dashboard-backup-2024-12-17 public_html/dashboard
```

**Option 2 - File Manager**:
1. Delete new dashboard folder
2. Rename backup folder back to `dashboard`

**Option 3 - FTP**:
1. Download backup to local machine (if not already saved)
2. Delete current dashboard
3. Re-upload backup

---

## Monthly Update Process

DMI publishes monthly updates within 7 days of BLS CPI release (~13th of month).

### Update Steps

1. **Receive notification** (or check on schedule around 20th of month)

2. **On local machine**:
   ```bash
   cd /path/to/dmi
   git pull origin main  # Get latest code
   ./venv/bin/python -m scripts.compute_dmi  # Run latest computation
   ./prepare_deployment.sh  # Generate new deployment package
   ```

3. **Backup current production** (see Rollback section)

4. **Upload new files**:
   - Upload `deploy/` contents (overwrites old files)
   - Or upload new dmi-v0.1.10-deployment.zip and extract

5. **Run smoke test checklist**

6. **Verify health.json** shows new period

7. **Delete backup** (after 1 week if no issues)

### Automation (Advanced)

If you have SSH access and Python on server:

```bash
# Add to crontab (runs monthly on 20th at 2am)
0 2 20 * * cd /path/to/dmi && git pull && ./venv/bin/python -m scripts.compute_dmi && ./prepare_deployment.sh && cp -r deploy/* /var/www/html/dashboard/
```

---

## Subdomain vs Subdirectory

### Subdirectory Approach
**URL**: `https://yourdomain.com/dashboard/`

**Pros**:
- Easier setup (just upload to folder)
- No DNS changes needed
- Shares main domain SSL certificate

**Cons**:
- Longer URL
- May conflict with WordPress paths

**Use when**: Simplicity is priority

### Subdomain Approach
**URL**: `https://data.yourdomain.com/`

**Pros**:
- Cleaner URL
- Isolated from main site
- Can have separate SSL if needed

**Cons**:  
- Requires subdomain creation in control panel
- May need DNS propagation (15-60 minutes)
- Separate SSL certificate (or wildcard)

**Use when**: Professional appearance matters

---

## SSL/HTTPS Configuration

Most modern hosts provide free SSL (Let's Encrypt).

### Enable HTTPS

1. **cPanel**: SSL/TLS → Install Let's Encrypt SSL
2. **Plesk**: SSL/TLS Certificates → Install free certificate
3. **Manual**: Use Certbot or similar

### Force HTTPS

Uncomment in `.htaccess`:

```apache
RewriteEngine On
RewriteCond %{HTTPS} off
RewriteRule ^(.*)$ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]
```

---

## Performance Optimization

Dashboard is already optimized, but for extra performance:

### CDN (Optional)
- Cloudflare (free tier) - caches static files globally
- Reduces load times for international visitors

### Compression
- `.htaccess` enables gzip (if Apache mod_deflate available)
- Reduces file sizes by ~70%

### Caching
- `.htaccess` sets browser cache headers
- Reduces repeat visits load time

---

## Security Considerations

Dashboard is static (no server-side code), so attack surface is minimal.

**Already Implemented**:
- ✅ X-Frame-Options (prevents clickjacking)
- ✅ X-XSS-Protection (XSS prevention)
- ✅ X-Content-Type-Options (MIME sniffing protection)
- ✅ CORS headers (controlled data access)

**Optional Enhancements**:
- Use HTTPS (strongly recommended)
- Enable Cloudflare (DDoS protection)
- Disable directory browsing (already in .htaccess)

---

## Support & Resources

**Documentation**:
- API Guide: `docs/API.md`
- Methodology: `docs/DMI_Methodology_Note.md`
- Release Calendar: `docs/RELEASE_CALENDAR.md`

**GitHub**: https://github.com/dmianalysis/dmi

**Health Check**: Always test `https://yourdomain.com/path/health.json` first when troubleshooting

---

**Last Updated**: December 17, 2025  
**For**: DMI v0.1.10
