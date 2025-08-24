package com.locationapp.auth.security;

import com.locationapp.auth.entity.User;
import io.jsonwebtoken.*;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import javax.crypto.SecretKey;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.Date;

@Component
public class JwtTokenProvider {

    @Value("${app.jwt.secret:your-super-secret-jwt-key-change-in-production}")
    private String jwtSecret;

    @Value("${app.jwt.access-token-expiration:900000}") // 15 minutes
    private int accessTokenExpiration;

    @Value("${app.jwt.refresh-token-expiration:604800000}") // 7 days
    private int refreshTokenExpiration;

    private SecretKey getSigningKey() {
        return Keys.hmacShaKeyFor(jwtSecret.getBytes());
    }

    public String generateAccessToken(User user) {
        Date expiry = new Date(System.currentTimeMillis() + accessTokenExpiration);
        
        return Jwts.builder()
            .setSubject(user.getId().toString())
            .claim("username", user.getUsername())
            .claim("email", user.getEmail())
            .claim("roles", user.getRoles())
            .claim("type", "access")
            .setIssuedAt(new Date())
            .setExpiration(expiry)
            .signWith(getSigningKey())
            .compact();
    }

    public String generateRefreshToken(User user) {
        Date expiry = new Date(System.currentTimeMillis() + refreshTokenExpiration);
        
        return Jwts.builder()
            .setSubject(user.getId().toString())
            .claim("type", "refresh")
            .setIssuedAt(new Date())
            .setExpiration(expiry)
            .signWith(getSigningKey())
            .compact();
    }

    public Long getUserIdFromToken(String token) {
        Claims claims = Jwts.parser()
            .setSigningKey(getSigningKey())
            .build()
            .parseClaimsJws(token)
            .getBody();
        
        return Long.parseLong(claims.getSubject());
    }

    public long getExpirationFromToken(String token) {
        Claims claims = Jwts.parser()
            .setSigningKey(getSigningKey())
            .build()
            .parseClaimsJws(token)
            .getBody();
        
        return claims.getExpiration().getTime();
    }

    public boolean validateToken(String token) {
        try {
            Jwts.parser()
                .setSigningKey(getSigningKey())
                .build()
                .parseClaimsJws(token);
            return true;
        } catch (JwtException | IllegalArgumentException e) {
            return false;
        }
    }
}